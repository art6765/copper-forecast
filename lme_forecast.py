"""
lme_forecast.py — прогноз цены меди LME 3M (Этап 1).

Контекст: история LME 3M (через Westmetall) накапливается с нуля. Пока её мало
(~100+ дней), полноценный ML на LME невозможен (порог обучения — ~200 наблюдений).
Поэтому LME-прогноз строится двумя способами:

1. ОСНОВНОЙ — через зрелую COMEX-модель (5 лет) + коррекция на премию COMEX-LME.
   По определению премии:  COMEX(USD/т) / LME_3M = 1 + премия/100
   ⇒ LME_3M ≈ COMEX(USD/т) / (1 + премия/100).
   Допущение: премия сохраняется на горизонте (для Этапа 1 приемлемо).
   Поскольку и P0, и прогноз делятся на один множитель, процентное изменение
   (Δ%) и вероятность роста переносятся из COMEX-прогноза без изменений.

2. ПРЯМОЙ — GBM напрямую на накопленном ряду LME 3M (короткие горизонты).
   Это «второе мнение» из реальных LME-данных, без опоры на COMEX.

По мере накопления истории (Этап 3) автоматически подключатся ARIMA и ML.

Зависимости: pandas + models.forecast_gbm + data_loader.LB_PER_TON. Новых нет.
"""
from __future__ import annotations

from typing import Dict, Optional

import pandas as pd

from data_loader import LB_PER_TON
from models import HORIZONS, forecast_gbm

# Пороги доступности моделей по числу накопленных дневных точек LME.
GBM_MIN_DAYS = 60       # GBM: дрейф+волатильность за 60 дней
ARIMA_MIN_DAYS = 150    # ARIMA(1,1,1) на лог-цене — разумна от ~150
ML_MIN_DAYS = 200       # XGBoost/MLP: порог обучения (см. backtest.py)


def lme_series(raw: pd.DataFrame) -> pd.Series:
    """Накопленный ряд LME 3M (USD/т)."""
    if "lme_3m" not in raw.columns:
        return pd.Series(dtype=float)
    return raw["lme_3m"].dropna()


def current_premium_pct(raw: pd.DataFrame) -> Optional[float]:
    """Текущая премия COMEX над LME 3M, %. None если данных нет."""
    if "comex_lme_premium_pct" not in raw.columns:
        return None
    s = raw["comex_lme_premium_pct"].dropna()
    return float(s.iloc[-1]) if len(s) else None


def data_status(raw: pd.DataFrame) -> Dict:
    """Сколько дней LME накоплено и какие модели уже доступны."""
    s = lme_series(raw)
    n = int(len(s))
    return {
        "n_days": n,
        "first": s.index.min().date().isoformat() if n else None,
        "last": s.index.max().date().isoformat() if n else None,
        "gbm_ok": n >= GBM_MIN_DAYS,
        "arima_ok": n >= ARIMA_MIN_DAYS,
        "ml_ok": n >= ML_MIN_DAYS,
        "ml_eta_days": max(0, ML_MIN_DAYS - n),
    }


def comex_to_lme_df(df_fc_comex: pd.DataFrame,
                    premium_pct: float) -> pd.DataFrame:
    """Перевести COMEX-прогноз (forecasts_to_dataframe) в LME-эквивалент, USD/т.

    df_fc_comex — таблица с колонками forecasts_to_dataframe (цены в USD/lb).
    Берём ансамбль/модели как есть и пересчитываем цены:
        LME(USD/т) = COMEX(USD/lb) * LB_PER_TON / (1 + премия/100)
    """
    factor = 1.0 / (1.0 + premium_pct / 100.0)
    price_cols = ["P0, USD/lb", "Точечный", "Медиана", "p10", "p25", "p75", "p90"]
    out_names = {
        "P0, USD/lb": "P0, USD/т", "Точечный": "Точечный, USD/т",
        "Медиана": "Медиана, USD/т", "p10": "p10, USD/т", "p25": "p25, USD/т",
        "p75": "p75, USD/т", "p90": "p90, USD/т",
    }
    rows = []
    for _, r in df_fc_comex.iterrows():
        row = {"Горизонт": r["Горизонт"], "Дней": r["Дней"], "Модель": r["Модель"]}
        for c in price_cols:
            if c in r:
                row[out_names[c]] = round(float(r[c]) * LB_PER_TON * factor)
        # Процентное изменение и P(↑) переносятся без изменений (премия постоянна)
        if "Δ, %" in r:
            row["Δ, %"] = round(float(r["Δ, %"]), 2)
        if "P(↑), %" in r:
            row["P(↑), %"] = round(float(r["P(↑), %"]), 1)
        rows.append(row)
    return pd.DataFrame(rows)


def forecast_lme_gbm(raw: pd.DataFrame) -> pd.DataFrame:
    """Прямой GBM-прогноз на ряду LME 3M по всем горизонтам (USD/т).
    Возвращает пустой DataFrame, если данных меньше GBM_MIN_DAYS."""
    s = lme_series(raw)
    if len(s) < GBM_MIN_DAYS:
        return pd.DataFrame()
    rows = []
    for h in HORIZONS:
        try:
            fc = forecast_gbm(s, h["days"])
            rows.append({
                "Горизонт": h["label"], "Дней": h["days"],
                "P0, USD/т": round(fc.p0),
                "p10, USD/т": round(fc.p10),
                "Точечный, USD/т": round(fc.point),
                "p90, USD/т": round(fc.p90),
                "Δ, %": round(fc.change_pct, 2),
                "P(↑), %": round(fc.prob_up * 100, 1),
            })
        except Exception:
            pass
    return pd.DataFrame(rows)


def comex_lme_compare(raw: pd.DataFrame, days: int = 120) -> pd.DataFrame:
    """Сравнительный ряд COMEX (USD/т) и LME 3M (USD/т) за последние `days`
    для графика. COMEX = copper(USD/lb) * LB_PER_TON."""
    cols = {}
    if "copper" in raw.columns:
        cols["COMEX (USD/т)"] = raw["copper"] * LB_PER_TON
    if "lme_3m" in raw.columns:
        cols["LME 3M (USD/т)"] = raw["lme_3m"]
    if not cols:
        return pd.DataFrame()
    df = pd.DataFrame(cols).dropna(how="all").tail(days)
    return df
