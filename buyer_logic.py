"""
buyer_logic.py — логика «вердикта закупщика» поверх прогнозов модели.

Превращает технический прогноз (медиана, коридор, P↑) в простой совет:
  Покупать / Срочно покупать / Наблюдать / Подождать.

ВАЖНО — логика с точки зрения ЗАКУПЩИКА (инвертирована относительно трейдера):
  - Прогноз ВВЕРХ  → цена вырастет → надо брать СЕЙЧАС (Покупать / Срочно).
  - Прогноз ВНИЗ   → цена упадёт   → можно ПОДОЖДАТЬ (купишь дешевле).
  - Прогноз ПЛОСКО → Наблюдать (без спешки).

Цвета: зелёный = покупать (выгодно), жёлтый = наблюдать, красный = подождать
(риск переплаты, если купить сейчас).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

LB_PER_TON = 2204.62262

# Метаданные вердиктов (микрокопия как в прототипе CopperCast)
VERDICT_META = {
    "buy":    {"label": "Покупать",        "tone": "ok",   "ru": "Хорошая цена",
               "icon": "↑", "color": "#198754"},
    "urgent": {"label": "Срочно покупать", "tone": "ok",   "ru": "Окно закрывается",
               "icon": "⇈", "color": "#198754"},
    "watch":  {"label": "Наблюдать",       "tone": "warn", "ru": "Без спешки",
               "icon": "—", "color": "#F59E0B"},
    "wait":   {"label": "Подождать",       "tone": "wait", "ru": "Риск переплаты",
               "icon": "↓", "color": "#E00613"},
}


@dataclass
class Verdict:
    key: str               # buy / urgent / watch / wait
    label: str
    tone: str              # ok / warn / wait
    ru: str
    icon: str
    color: str
    horizon_key: str
    horizon_label: str
    spot_usd_t: float      # текущая цена USD/т
    median_usd_t: float    # медианный прогноз USD/т
    p10_usd_t: float
    p90_usd_t: float
    change_pct: float      # прогноз vs спот
    prob_up: float         # P(↑), %
    confidence: int        # 0-100, уверенность
    headline: str          # одна строка вердикта
    why: str               # развёрнутое «почему»


def _verdict_key(change_pct: float) -> str:
    """Определяет вердикт по ожидаемому изменению цены (с точки зрения закупщика)."""
    if change_pct >= 5.0:
        return "urgent"      # цена сильно вырастет → срочно фиксировать
    elif change_pct >= 1.5:
        return "buy"         # умеренный рост → брать сейчас
    elif change_pct <= -2.0:
        return "wait"        # цена упадёт → подождать
    else:
        return "watch"       # плоско → наблюдать


def _confidence(p10: float, p90: float, median: float,
                regime_calm_prob: Optional[float]) -> int:
    """Уверенность 0-100: узкий коридор + спокойный режим = выше."""
    # Относительная ширина коридора (чем уже — тем увереннее)
    rel_width = (p90 - p10) / median if median else 1.0
    # rel_width ~0.05 (узкий) → высокая, ~0.40 (широкий) → низкая
    width_score = max(0.0, min(1.0, 1.0 - rel_width / 0.45))
    # Вклад режима
    regime_score = regime_calm_prob if regime_calm_prob is not None else 0.6
    conf = 0.6 * width_score + 0.4 * regime_score
    return int(round(max(0.30, min(0.95, conf)) * 100))


HORIZON_SUB = {
    "h_3d":  ("3 дня", "ближайшая поставка"),
    "h_10d": ("10 дней", "спот-закупка"),
    "h_1m":  ("1 месяц", "месячный контракт"),
    "h_3m":  ("3 месяца", "квартальный контракт"),
    "h_6m":  ("6 месяцев", "полугодовой контракт"),
}


def compute_verdict(forecasts: Dict, horizon_key: str, spot_usd_lb: float,
                    regime_calm_prob: Optional[float] = None,
                    ensemble_name: str = "Ensemble") -> Optional[Verdict]:
    """Строит вердикт для одного горизонта из результата forecast_all_horizons.

    forecasts — {horizon_key: {model_name: HorizonForecast}}.
    """
    if horizon_key not in forecasts:
        return None
    models = forecasts[horizon_key]
    f = models.get(ensemble_name) or next(iter(models.values()), None)
    if f is None:
        return None

    spot_t = spot_usd_lb * LB_PER_TON
    median_t = f.median * LB_PER_TON
    p10_t = f.p10 * LB_PER_TON
    p90_t = f.p90 * LB_PER_TON
    change_pct = (f.median - spot_usd_lb) / spot_usd_lb * 100
    prob_up = f.prob_up * 100

    vkey = _verdict_key(change_pct)
    meta = VERDICT_META[vkey]
    conf = _confidence(p10_t, p90_t, median_t, regime_calm_prob)
    hlabel, hsub = HORIZON_SUB.get(horizon_key, (horizon_key, ""))

    # Микрокопия headline / why
    headline, why = _narrative(vkey, change_pct, prob_up, hlabel)

    return Verdict(
        key=vkey, label=meta["label"], tone=meta["tone"], ru=meta["ru"],
        icon=meta["icon"], color=meta["color"],
        horizon_key=horizon_key, horizon_label=hlabel,
        spot_usd_t=spot_t, median_usd_t=median_t,
        p10_usd_t=p10_t, p90_usd_t=p90_t,
        change_pct=change_pct, prob_up=prob_up, confidence=conf,
        headline=headline, why=why,
    )


def _narrative(vkey: str, change_pct: float, prob_up: float,
               hlabel: str) -> tuple:
    """Генерирует headline + развёрнутое «почему» простым языком."""
    chg = f"{change_pct:+.1f}%"
    if vkey == "urgent":
        head = "Риск роста цены — фиксируйте заранее"
        why = (f"Модель ожидает рост на {chg} к сроку «{hlabel}». "
               f"Верх коридора заметно выше текущей цены. "
               f"Если поставка нужна к этому сроку — выгоднее законтрактовать сейчас, "
               f"пока цена ниже.")
    elif vkey == "buy":
        head = "Цена скорее вырастет — брать сейчас выгоднее"
        why = (f"Прогноз умеренно вверх ({chg}) на горизонте «{hlabel}», "
               f"вероятность роста {prob_up:.0f}%. "
               f"Зафиксировать цену сейчас выгоднее, чем ждать.")
    elif vkey == "wait":
        head = "Вероятна коррекция — лучше подождать"
        why = (f"Модель видит снижение цены ({chg}) к сроку «{hlabel}». "
               f"Если поставка не срочная — дождитесь отката, вход ниже вероятен.")
    else:  # watch
        head = "Цена держится — спешить некуда"
        why = (f"На горизонте «{hlabel}» модели не видят значимого движения "
               f"({chg}). Текущая цена близка к справедливой — окно стабильно, "
               f"можно наблюдать.")
    return head, why


def all_verdicts(forecasts: Dict, spot_usd_lb: float,
                 regime_calm_prob: Optional[float] = None) -> Dict[str, Verdict]:
    """Вердикты по всем горизонтам — для селектора горизонта."""
    out = {}
    for hk in ["h_3d", "h_10d", "h_1m", "h_3m", "h_6m"]:
        v = compute_verdict(forecasts, hk, spot_usd_lb, regime_calm_prob)
        if v:
            out[hk] = v
    return out


def buyer_factors(raw_df: pd.DataFrame) -> List[Dict]:
    """Факторы для блока «Почему такой совет» — простым языком.

    Возвращает список {title, value, tone} где tone: ok/warn/wait.
    """
    factors = []

    # 1. Изменение цены за неделю
    if len(raw_df) > 6:
        wk = (raw_df["copper"].iloc[-1] / raw_df["copper"].iloc[-6] - 1) * 100
        tone = "wait" if wk > 3 else "warn" if wk > 1 else "ok"
        factors.append({"title": "Цена за неделю", "value": f"{wk:+.1f}%",
                        "tone": tone})

    # 2. COT — позиции спекулянтов
    if "mm_net_long_pct" in raw_df.columns and raw_df["mm_net_long_pct"].notna().any():
        pct = float(raw_df["mm_net_long_pct"].dropna().iloc[-1])
        tone = "wait" if pct > 35 else "warn" if pct > 25 else "ok"
        factors.append({"title": "Спекулянты (COT)", "value": f"{pct:.0f}% от рынка",
                        "tone": tone})

    # 3. LME запасы
    if "lme_stock_total" in raw_df.columns and raw_df["lme_stock_total"].notna().any():
        stock = float(raw_df["lme_stock_total"].dropna().iloc[-1])
        # Низкие запасы → дефицит → bullish (покупать)
        tone = "wait" if stock < 150000 else "warn" if stock < 300000 else "ok"
        factors.append({"title": "Запасы LME", "value": f"{stock/1000:.0f} тыс. т",
                        "tone": tone})

    # 4. Доллар (DXY) — динамика за 20 дней
    if "dxy" in raw_df.columns and len(raw_df) > 21:
        dxy_chg = (raw_df["dxy"].iloc[-1] / raw_df["dxy"].iloc[-21] - 1) * 100
        # Доллар растёт → медь под давлением
        tone = "wait" if dxy_chg > 1 else "ok" if dxy_chg < -1 else "warn"
        label = "крепкий" if dxy_chg > 1 else "слабеет" if dxy_chg < -1 else "стабилен"
        factors.append({"title": "Доллар (DXY)", "value": label, "tone": tone})

    # 5. Премия COMEX/LME (тарифный риск)
    if "comex_lme_premium_pct" in raw_df.columns and raw_df["comex_lme_premium_pct"].notna().any():
        prem = float(raw_df["comex_lme_premium_pct"].dropna().iloc[-1])
        tone = "wait" if prem > 8 else "warn" if prem > 3 else "ok"
        factors.append({"title": "Премия COMEX/LME", "value": f"{prem:+.1f}%",
                        "tone": tone})

    return factors


if __name__ == "__main__":
    import datetime as dt
    from data_loader import load_all
    from models import forecast_all_horizons

    start = (dt.date.today() - dt.timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    results = forecast_all_horizons(raw, use_xgb=True, use_mlp=False,
                                     use_arima=True, use_gbm=True)
    spot_lb = float(raw["copper"].iloc[-1])

    print(f"Спот: {spot_lb:.4f} USD/lb = {spot_lb*LB_PER_TON:,.0f} USD/т\n")
    verdicts = all_verdicts(results, spot_lb, regime_calm_prob=0.99)
    for hk, v in verdicts.items():
        print(f"{v.horizon_label:10s} | {v.label:16s} ({v.ru:18s}) | "
              f"{v.median_usd_t:,.0f} USD/т ({v.change_pct:+.1f}%) | "
              f"conf {v.confidence}%")
        print(f"             └─ {v.headline}")

    print("\nФакторы:")
    for f in buyer_factors(raw):
        print(f"  [{f['tone']:4s}] {f['title']}: {f['value']}")
