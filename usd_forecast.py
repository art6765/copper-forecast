"""
usd_forecast.py — прогноз официального курса доллара ЦБ РФ (USD/RUB).

Используется ТОТ ЖЕ движок, что и для меди: подменяем целевой ряд
(copper → usdrub) и переиспользуем forecast_all_horizons
(GBM + ARIMA + XGBoost + MLP + ансамбль). Это приём из lme_forecast.py.

В отличие от LME, история курса ЦБ РФ длинная (несколько лет за один запрос),
поэтому «дозревание» и мостик через зрелую модель не нужны — все модели
доступны сразу.

Прогноз курса нужен для двух задач:
  1. пересчёт прогнозной цены меди в рубли (карточка закупщика);
  2. самостоятельный ориентир по валюте на тех же горизонтах.

Зависимости: pandas + models.forecast_all_horizons. Новых пакетов нет.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

from models import forecast_all_horizons, forecasts_to_dataframe, HORIZONS

# Минимум дневных точек для осмысленного прогноза курса.
MIN_DAYS = 60

# Окно обучения модели курса под ТЕКУЩИЙ монетарный режим рубля. С 2022 курс
# пережил структурные сломы (капитальный контроль, обязательная продажа валюты
# экспортёрами, шок февраля-2022 с пиком 120+ и откатом). Обучать на всём ряду —
# значит смешивать несовместимые режимы и завышать волатильность. Поэтому по
# умолчанию берём последние ~3 года: это отсекает шок 2022 и оставляет данные
# действующего управляемого режима. Если истории меньше — используем всё.
RECENCY_YEARS = 3.0
MIN_RECENCY_DAYS = 380   # не сужаем агрессивнее, чем до ~1.5 лет

# Переименование ценовых колонок forecasts_to_dataframe в рублёвые подписи.
_RUB_RENAME = {
    "P0, USD/lb": "P0, ₽", "Точечный": "Точечный, ₽", "Медиана": "Медиана, ₽",
    "p10": "p10, ₽", "p25": "p25, ₽", "p75": "p75, ₽", "p90": "p90, ₽",
}


def usdrub_series(raw: pd.DataFrame) -> pd.Series:
    """Накопленный ряд официального курса USD/RUB (руб за 1 доллар)."""
    if "usdrub" not in raw.columns:
        return pd.Series(dtype=float)
    return raw["usdrub"].dropna()


def current_usdrub(raw: pd.DataFrame) -> Optional[float]:
    """Последний известный курс USD/RUB. None, если данных нет."""
    s = usdrub_series(raw)
    return float(s.iloc[-1]) if len(s) else None


def data_status(raw: pd.DataFrame) -> Dict:
    """Сколько дней курса накоплено и доступен ли прогноз."""
    s = usdrub_series(raw)
    n = int(len(s))
    return {
        "n_days": n,
        "first": s.index.min().date().isoformat() if n else None,
        "last": s.index.max().date().isoformat() if n else None,
        "ready": n >= MIN_DAYS,
    }


def _usdrub_as_raw(raw: pd.DataFrame,
                   recency_years: float = RECENCY_YEARS) -> pd.DataFrame:
    """Копия raw с целевым рядом = USD/RUB вместо меди, выровненная по датам
    курса. Позволяет переиспользовать build_features / forecast_all_horizons.
    Кросс-факторы (DXY, Brent, нефть, золото, ставка ЦБ, carry) релевантны рублю
    и остаются как фичи. Медные OHLC/объём убираем — к курсу не относятся.

    Окно обучения сужается до последних recency_years лет (режимная очистка —
    см. RECENCY_YEARS), но не агрессивнее MIN_RECENCY_DAYS точек.
    """
    fx = usdrub_series(raw)
    sub = raw.reindex(fx.index).copy()
    sub["copper"] = fx
    for col in ["copper_high", "copper_low", "copper_volume"]:
        if col in sub.columns:
            sub = sub.drop(columns=col)
    # Режимное окно: оставляем только последние recency_years лет,
    # если данных заметно больше (иначе теряем выборку для длинных горизонтов).
    if recency_years and len(sub) > MIN_RECENCY_DAYS:
        cutoff = sub.index.max() - pd.Timedelta(days=int(recency_years * 365))
        trimmed = sub.loc[sub.index >= cutoff]
        if len(trimmed) >= MIN_RECENCY_DAYS:
            sub = trimmed
    return sub


def forecast_usdrub(raw: pd.DataFrame, use_xgb: bool = True, use_mlp: bool = True,
                    use_arima: bool = True, use_gbm: bool = True,
                    recency_years: float = RECENCY_YEARS
                    ) -> Dict[str, Dict]:
    """Прогноз курса USD/RUB по всем горизонтам из HORIZONS.

    Возвращает тот же вложенный словарь, что и forecast_all_horizons:
        {horizon_key: {model_name: HorizonForecast}}
    Значения p0/point/p10/p90 — уже в рублях за доллар (ряд курса в ₽).
    Пустой словарь, если данных меньше MIN_DAYS или произошёл сбой.
    """
    fx = usdrub_series(raw)
    if len(fx) < MIN_DAYS:
        return {}
    try:
        sub = _usdrub_as_raw(raw, recency_years=recency_years)
        return forecast_all_horizons(
            sub, use_xgb=use_xgb, use_mlp=use_mlp,
            use_arima=use_arima, use_gbm=use_gbm,
        )
    except Exception:
        return {}


def forecast_usdrub_df(raw: pd.DataFrame, **kwargs) -> pd.DataFrame:
    """Прогноз курса в виде таблицы (forecasts_to_dataframe) с рублёвыми подписями.
    Пустой DataFrame, если прогноз недоступен."""
    results = forecast_usdrub(raw, **kwargs)
    if not results:
        return pd.DataFrame()
    df = forecasts_to_dataframe(results)
    return df.rename(columns=_RUB_RENAME)


def usdrub_history(raw: pd.DataFrame, days: int = 252) -> pd.Series:
    """Последние `days` точек курса USD/RUB — для графика прогнозной кривой."""
    return usdrub_series(raw).tail(days)


if __name__ == "__main__":
    import logging
    import datetime as dt
    logging.basicConfig(level=logging.WARNING)
    from data_loader import load_all

    start = (dt.date.today() - dt.timedelta(days=4 * 365)).strftime("%Y-%m-%d")
    raw = load_all(start=start, include_cot=False, include_lme_stocks=False,
                   include_lme_price=False, include_fred=False)
    print("Статус данных курса:", data_status(raw))
    print(f"Текущий курс: {current_usdrub(raw):.2f} ₽/$\n")
    df = forecast_usdrub_df(raw)
    if not df.empty:
        ens = df[df["Модель"] == "Ensemble"]
        cols = [c for c in ["Горизонт", "Дней", "P0, ₽", "p10, ₽",
                            "Точечный, ₽", "p90, ₽", "Δ, %", "P(↑), %"]
                if c in ens.columns]
        print(ens[cols].to_string(index=False))
    else:
        print("Прогноз курса недоступен (мало данных).")
