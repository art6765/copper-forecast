"""
procurement.py — превращение прогноза в план закупки и доказательство экономии.

Два инструмента поверх уже готовых прогнозов и логики закупщика:

1. plan_purchase() — ПЛАНИРОВЩИК: по потребности (тонн/мес × срок) строит график
   закупки траншами (сколько брать сейчас и сколько откладывать), считает
   ожидаемую стоимость в рублях с коридором и экономию против «купить всё сейчас»
   и «покупать равномерно». Использует recommend_allocation (та же логика, что в
   карточке) и прогноз цены меди + курса по горизонтам.

2. backtest_strategy() — БЭКТЕСТ СТРАТЕГИИ: на исторических прогнозах
   (walk_forward) сравнивает «следовать системе» (брать больше перед ростом,
   минимум перед падением) против «покупать равномерно». Веса берутся ТОЛЬКО из
   информации, доступной на дату решения (без подглядывания), а фактические цены
   показывают реальную реализованную экономию. Это денежное доказательство пользы.

Зависимости: numpy, pandas, buyer_logic, data_loader. Новых пакетов нет.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from data_loader import LB_PER_TON
from buyer_logic import _verdict_key, recommend_allocation


# ---------------------------------------------------------------------------
#  1. Планировщик закупки (forward)
# ---------------------------------------------------------------------------

def _interp(month_targets: np.ndarray, anchors_m: List[float],
            anchors_v: List[float]) -> np.ndarray:
    """Линейная интерполяция значений по месяцам-вперёд из опорных точек
    горизонтов. anchors_m отсортированы по возрастанию (вкл. 0 = «сейчас»)."""
    am = np.asarray(anchors_m, dtype=float)
    av = np.asarray(anchors_v, dtype=float)
    order = np.argsort(am)
    return np.interp(month_targets, am[order], av[order])


def plan_purchase(need_per_month: float, n_months: int,
                  spot_usd_t: float, fx_now: float,
                  anchors_m: List[float], anchors_price: List[float],
                  anchors_p10: List[float], anchors_p90: List[float],
                  anchors_fx: List[float],
                  alloc: Dict) -> Dict:
    """Построить план закупки.

    need_per_month — потребность, тонн/мес; n_months — горизонт планирования.
    spot_usd_t/fx_now — текущая цена меди (USD/т) и курс (₽/$).
    anchors_* — опорные точки прогноза по месяцам-вперёд (вкл. 0 = сейчас):
        anchors_m — месяцы, anchors_price/p10/p90 — цена меди USD/т и коридор,
        anchors_fx — прогнозный курс ₽/$.
    alloc — результат recommend_allocation (immediate_pct, tranches, floor_pct).

    Возвращает dict: schedule (список траншей), totals (ожид./мин./макс. ₽),
    baselines (купить всё сейчас, равномерно) и savings (₽ и %).
    """
    n_months = max(1, int(n_months))
    total_t = float(need_per_month) * n_months
    imm_pct = float(alloc.get("immediate_pct", 50)) / 100.0
    n_tr = max(1, int(alloc.get("tranches", 3)))

    now_t = round(total_t * imm_pct, 1)
    rest_t = max(0.0, total_t - now_t)

    # Будущие транши равными долями, равномерно распределены по сроку (мес. 1..N)
    tr_months = [round((i + 1) * n_months / (n_tr + 1), 2) for i in range(n_tr)]
    tr_t = round(rest_t / n_tr, 1) if n_tr else 0.0

    months_arr = np.asarray(tr_months, dtype=float)
    pr = _interp(months_arr, anchors_m, anchors_price)
    lo = _interp(months_arr, anchors_m, anchors_p10)
    hi = _interp(months_arr, anchors_m, anchors_p90)
    fx = _interp(months_arr, anchors_m, anchors_fx)

    schedule: List[Dict] = []
    # Транш «сейчас» — цена известна, коридора нет
    now_cost = now_t * spot_usd_t * fx_now
    schedule.append({
        "when": "Сейчас", "month": 0.0, "tonnes": now_t,
        "price_usd_t": spot_usd_t, "fx": fx_now,
        "cost_rub": now_cost, "cost_low": now_cost, "cost_high": now_cost,
    })
    for i in range(n_tr):
        c = tr_t * float(pr[i]) * float(fx[i])
        c_lo = tr_t * float(lo[i]) * float(fx[i])
        c_hi = tr_t * float(hi[i]) * float(fx[i])
        schedule.append({
            "when": f"через ~{tr_months[i]:.1f} мес", "month": tr_months[i],
            "tonnes": tr_t, "price_usd_t": float(pr[i]), "fx": float(fx[i]),
            "cost_rub": c, "cost_low": c_lo, "cost_high": c_hi,
        })

    exp = sum(s["cost_rub"] for s in schedule)
    low = sum(s["cost_low"] for s in schedule)
    high = sum(s["cost_high"] for s in schedule)

    # База 1: купить весь объём прямо сейчас по текущей цене
    buy_now_all = total_t * spot_usd_t * fx_now
    # База 2: покупать равномерно по месяцам (DCA) по прогнозной цене каждого мес.
    dca_months = np.arange(1, n_months + 1, dtype=float)
    dca_pr = _interp(dca_months, anchors_m, anchors_price)
    dca_fx = _interp(dca_months, anchors_m, anchors_fx)
    dca_total = float(np.sum(need_per_month * dca_pr * dca_fx))

    return {
        "total_t": total_t, "now_t": now_t, "tranche_t": tr_t, "n_tranches": n_tr,
        "schedule": schedule,
        "expected_rub": exp, "low_rub": low, "high_rub": high,
        "buy_now_all_rub": buy_now_all, "dca_rub": dca_total,
        "save_vs_now_rub": buy_now_all - exp,
        "save_vs_now_pct": (buy_now_all - exp) / buy_now_all * 100 if buy_now_all else 0.0,
        "save_vs_dca_rub": dca_total - exp,
        "save_vs_dca_pct": (dca_total - exp) / dca_total * 100 if dca_total else 0.0,
        "avg_price_rub_t": exp / total_t if total_t else 0.0,
    }


# ---------------------------------------------------------------------------
#  2. Бэктест стратегии закупщика (historical proof)
# ---------------------------------------------------------------------------

def _buy_weight(p0: float, point: float, p10: float, p90: float) -> float:
    """Доля закупки на дату решения по той же логике, что в карточке:
    сильнее перед ожидаемым ростом, минимум (якорь) перед падением.
    Использует ТОЛЬКО прогноз на дату (без подглядывания в факт)."""
    if not p0 or p0 <= 0:
        return 0.0
    change_pct = (point / p0 - 1) * 100
    band_pct = (p90 - p10) / 2 / point * 100 if point else None
    key = _verdict_key(change_pct)
    alloc = recommend_allocation(key, change_pct=change_pct, band_pct=band_pct)
    return float(alloc.get("immediate_pct", 50))


def backtest_strategy(ens_h: pd.DataFrame, usdrub: Optional[pd.Series] = None
                      ) -> Optional[Dict]:
    """Сравнить стратегию «следовать системе» против «покупать равномерно».

    ens_h — DataFrame одного горизонта из walk_forward (predictions['Ensemble'][H]):
    индекс — дата решения, колонки p0/actual/point/p10/p90 (цена в USD/lb).
    usdrub — ряд курса ₽/$ (raw['usdrub']) для расчёта в рублях; опционально.

    Закупщик за период должен закупить весь объём. «Система» распределяет объём
    по дате решения весами _buy_weight (больше перед ростом), «равномерно» — поровну.
    Платим цену p0 на дату решения. Метрика — средневзвешенная цена закупки.

    Возвращает dict со средними ценами (USD/т и ₽/т), экономией и рядом
    накопленной средней цены для графика. None, если данных мало.
    """
    if ens_h is None or ens_h.empty or len(ens_h) < 5:
        return None
    df = ens_h.dropna(subset=["p0", "point"]).copy()
    if len(df) < 5:
        return None
    df = df.sort_index()

    # Курс на дату решения (ffill); если нет — считаем только в USD
    if usdrub is not None and len(usdrub.dropna()):
        fx = usdrub.dropna().reindex(df.index, method="ffill")
        fx = fx.fillna(method="bfill")
    else:
        fx = pd.Series(1.0, index=df.index)
    have_rub = usdrub is not None and float(fx.notna().mean()) > 0.5

    price_t = df["p0"].astype(float) * LB_PER_TON                # USD/т на дату
    weights = np.array([_buy_weight(r.p0, r.point, r.p10, r.p90)
                        for r in df.itertuples()], dtype=float)
    weights = np.where(weights > 0, weights, 0.0)
    if weights.sum() <= 0:
        return None
    eq = np.ones(len(df))                                        # равномерно

    sys_usd = float(np.sum(weights * price_t.values) / weights.sum())
    dca_usd = float(np.sum(eq * price_t.values) / eq.sum())

    out = {
        "n": int(len(df)),
        "first": df.index.min().date().isoformat(),
        "last": df.index.max().date().isoformat(),
        "sys_usd_t": sys_usd, "dca_usd_t": dca_usd,
        "save_usd_t": dca_usd - sys_usd,
        "save_pct": (dca_usd - sys_usd) / dca_usd * 100 if dca_usd else 0.0,
        "have_rub": have_rub,
    }
    if have_rub:
        price_rub = price_t.values * fx.values
        out["sys_rub_t"] = float(np.sum(weights * price_rub) / weights.sum())
        out["dca_rub_t"] = float(np.sum(eq * price_rub) / eq.sum())
        out["save_rub_t"] = out["dca_rub_t"] - out["sys_rub_t"]

    # Ряды накопленной средней цены (₽/т, иначе USD/т) — для графика «во времени»
    unit_price = (price_t.values * fx.values) if have_rub else price_t.values
    cum_w = np.cumsum(weights * unit_price) / np.cumsum(weights)
    cum_e = np.cumsum(eq * unit_price) / np.cumsum(eq)
    out["curve"] = pd.DataFrame(
        {"system": cum_w, "uniform": cum_e}, index=df.index)
    out["unit"] = "₽/т" if have_rub else "USD/т"
    return out
