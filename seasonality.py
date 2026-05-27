"""
seasonality.py — сезонный анализ цены меди.

Подходы:
1. **Месячная сезонность** — средняя доходность по месяцам за N лет.
2. **Day-of-week** — есть ли разница между понедельником и пятницей.
3. **STL-декомпозиция** — выделение тренда / сезонной компоненты / остатка.
4. **Event study** — среднее поведение цены вокруг типов событий из каталога.
5. **Сезонный прогноз** — historic-mean доходность для текущего календарного
   интервала.

Все методы — на основе наших же данных (HG=F + опционально FRED PCOPPUSDM
для длинной истории). Не требует платных подписок.
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")

MONTH_NAMES = {1: "Янв", 2: "Фев", 3: "Мар", 4: "Апр", 5: "Май", 6: "Июн",
                7: "Июл", 8: "Авг", 9: "Сен", 10: "Окт", 11: "Ноя", 12: "Дек"}
DOW_NAMES = {0: "Пн", 1: "Вт", 2: "Ср", 3: "Чт", 4: "Пт"}


# ====================================================================
#  1. Месячная сезонность
# ====================================================================

def monthly_returns(prices: pd.Series) -> pd.DataFrame:
    """Месячная доходность по парам (год, месяц).
    Возвращает DataFrame с колонками year, month, return_pct.
    """
    monthly = prices.resample("ME").last()  # последняя цена месяца
    ret = monthly.pct_change() * 100
    df = pd.DataFrame({"return_pct": ret}).dropna()
    df["year"] = df.index.year
    df["month"] = df.index.month
    return df.reset_index(drop=True)


def monthly_heatmap(prices: pd.Series) -> pd.DataFrame:
    """Heatmap-таблица: строки = годы, столбцы = месяцы, значения = доходность %."""
    df = monthly_returns(prices)
    pivot = df.pivot(index="year", columns="month", values="return_pct")
    pivot.columns = [MONTH_NAMES[m] for m in pivot.columns]
    return pivot


def monthly_avg(prices: pd.Series) -> pd.DataFrame:
    """Средняя/медианная доходность по месяцам. Сколько лет в выборке."""
    df = monthly_returns(prices)
    agg = df.groupby("month")["return_pct"].agg(["mean", "median", "std", "count"])
    agg.index = [MONTH_NAMES[m] for m in agg.index]
    agg.columns = ["Среднее, %", "Медиана, %", "Стд, %", "Лет"]
    return agg


def best_worst_months(prices: pd.Series) -> Tuple[str, str]:
    """Возвращает (best_month, worst_month) по средней доходности."""
    agg = monthly_avg(prices)
    return agg["Среднее, %"].idxmax(), agg["Среднее, %"].idxmin()


# ====================================================================
#  2. Day-of-week effects
# ====================================================================

def dow_avg(prices: pd.Series) -> pd.DataFrame:
    """Средняя доходность по дням недели (Пн-Пт)."""
    ret = np.log(prices / prices.shift(1)).dropna() * 100
    df = pd.DataFrame({"ret": ret, "dow": ret.index.dayofweek})
    agg = df.groupby("dow")["ret"].agg(["mean", "std", "count"])
    agg.index = [DOW_NAMES.get(d, str(d)) for d in agg.index]
    agg.columns = ["Среднее, %", "Стд, %", "Дней"]
    return agg


# ====================================================================
#  3. STL-декомпозиция
# ====================================================================

@dataclass
class STLResult:
    trend: pd.Series
    seasonal: pd.Series
    residual: pd.Series
    period: int


def stl_decompose(prices: pd.Series, period: int = 252) -> STLResult:
    """STL-декомпозиция: trend + seasonal + residual.

    period = 252 ≈ количество торговых дней в году (для годовой сезонности).
    Можно использовать 21 для месячной, 63 для квартальной.
    """
    from statsmodels.tsa.seasonal import STL

    # STL требует регулярного индекса — используем log(price), чтобы декомпозиция
    # была в "доходностной" семантике.
    log_p = np.log(prices.dropna())
    # Заполним пропуски, чтобы STL не упал
    log_p = log_p.asfreq("B").interpolate()

    stl = STL(log_p, period=period, robust=True)
    result = stl.fit()
    return STLResult(
        trend=result.trend.dropna(),
        seasonal=result.seasonal.dropna(),
        residual=result.resid.dropna(),
        period=period,
    )


# ====================================================================
#  4. Event study (на каталоге исторических событий)
# ====================================================================

def event_study(prices: pd.Series, event_dates: List[pd.Timestamp],
                before_days: int = 10, after_days: int = 30) -> pd.DataFrame:
    """Среднее поведение цены вокруг событий.

    Для каждой даты события t берём окно [-before, +after] бизнес-дней,
    нормируем цену на t=0, усредняем по событиям.

    Возвращает DataFrame с колонками: day (от -before до +after), avg_price (=1.0 на day=0),
    n_events, std_price.
    """
    series_list = []
    for ed in event_dates:
        ed = pd.Timestamp(ed)
        # Найдём ближайший бизнес-день
        loc = prices.index.searchsorted(ed)
        if loc >= len(prices) or loc == 0:
            continue
        center_idx = loc if prices.index[loc] == ed else max(0, loc - 1)
        # Окно
        start = max(0, center_idx - before_days)
        end = min(len(prices), center_idx + after_days + 1)
        window = prices.iloc[start:end]
        if len(window) < before_days + after_days + 1 - 2:
            continue
        # Нормируем на цену в день события
        norm = window / prices.iloc[center_idx]
        norm.index = range(start - center_idx, end - center_idx)
        series_list.append(norm)

    if not series_list:
        return pd.DataFrame(columns=["day", "avg_price", "std_price", "n_events"])

    aligned = pd.concat(series_list, axis=1)
    out = pd.DataFrame({
        "day": aligned.index,
        "avg_price": aligned.mean(axis=1).values,
        "std_price": aligned.std(axis=1).values,
        "n_events": aligned.notna().sum(axis=1).values,
    })
    return out


def event_study_by_type(prices: pd.Series, events_catalog,
                         before: int = 10, after: int = 30) -> Dict[str, pd.DataFrame]:
    """Группирует event_study по типу события из events.py каталога."""
    by_type: Dict[str, List[pd.Timestamp]] = {}
    for ev in events_catalog:
        by_type.setdefault(ev.type, []).append(pd.Timestamp(ev.date))

    out = {}
    for t, dates in by_type.items():
        if len(dates) >= 2:  # минимум 2 события для усреднения
            out[t] = event_study(prices, dates, before, after)
    return out


# ====================================================================
#  5. Сезонная фича для модели
# ====================================================================

def seasonal_signal(prices: pd.Series, horizon_days: int,
                    window_years: int = 5) -> pd.Series:
    """Для каждой даты t возвращает «исторический сезонный сигнал» —
    среднюю доходность за такой же календарный интервал в прошлом.

    Пример: для t = 2026-05-27, horizon = 21, window=5 лет:
    смотрим доходности (2025-05-27 → 2025-06-17), (2024-05-27 → 2024-06-17),
    (2023..2021) — берём среднее.
    """
    log_p = np.log(prices)
    target_ret = log_p.shift(-horizon_days) - log_p

    out = pd.Series(np.nan, index=prices.index, name=f"seasonal_h{horizon_days}")

    for t in prices.index:
        signals = []
        for k in range(1, window_years + 1):
            past_t = t - pd.DateOffset(years=k)
            # Найдём ближайший бизнес-день
            loc = prices.index.searchsorted(past_t)
            if loc >= len(prices):
                continue
            ret = target_ret.iloc[loc] if loc < len(target_ret) else np.nan
            if pd.notna(ret):
                signals.append(ret)
        if signals:
            out.loc[t] = np.mean(signals)

    return out


def current_seasonal_forecast(prices: pd.Series,
                               horizons_days: List[int] = None,
                               window_years: int = 5) -> Dict[int, Dict]:
    """Сезонный прогноз на текущий момент.

    Возвращает {H: {'mean_log_ret', 'std_log_ret', 'point_price', 'n_years'}}.
    """
    if horizons_days is None:
        horizons_days = [3, 10, 21, 63, 126]

    p0 = float(prices.iloc[-1])
    t = prices.index[-1]
    log_p = np.log(prices)
    out = {}

    for H in horizons_days:
        signals = []
        for k in range(1, window_years + 1):
            past_t = t - pd.DateOffset(years=k)
            loc = prices.index.searchsorted(past_t)
            if loc >= len(prices) or loc + H >= len(prices):
                continue
            past_log = log_p.iloc[loc]
            past_future_log = log_p.iloc[loc + H]
            signals.append(past_future_log - past_log)
        if signals:
            mean_ret = float(np.mean(signals))
            std_ret = float(np.std(signals, ddof=1)) if len(signals) > 1 else 0.0
            point = p0 * np.exp(mean_ret)
            out[H] = {
                "mean_log_ret": mean_ret,
                "std_log_ret": std_ret,
                "point_price": point,
                "change_pct": (point - p0) / p0 * 100,
                "n_years": len(signals),
            }
        else:
            out[H] = None

    return out


# ====================================================================
#  Demo
# ====================================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    import datetime as dt
    from data_loader import load_all

    start = (dt.date.today() - dt.timedelta(days=5 * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start, include_cot=False, include_lme_stocks=False,
                    include_fred=False, include_lme_price=False)
    prices = raw["copper"]

    print("=== Месячная сезонность (последние 5 лет) ===")
    agg = monthly_avg(prices)
    print(agg.round(2))
    best, worst = best_worst_months(prices)
    print(f"\nЛучший месяц: {best}, худший: {worst}")

    print("\n=== Day-of-week ===")
    print(dow_avg(prices).round(3))

    print("\n=== STL декомпозиция (period=252) ===")
    stl = stl_decompose(prices, period=252)
    print(f"  trend range: {stl.trend.min():.4f} → {stl.trend.max():.4f}")
    print(f"  seasonal range: {stl.seasonal.min():.4f} → {stl.seasonal.max():.4f}")
    print(f"  current seasonal effect: {stl.seasonal.iloc[-1]*100:+.2f}%")

    print("\n=== Сезонный прогноз ===")
    sf = current_seasonal_forecast(prices)
    for H, info in sf.items():
        if info:
            print(f"  H={H:3d}: point = {info['point_price']:.4f} "
                  f"({info['change_pct']:+.2f}%, n={info['n_years']})")
