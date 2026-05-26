"""
backtest.py — walk-forward валидация моделей прогноза цены меди.

Стратегия: расширяющееся окно тренировки.
- Берём первые `train_min_years` лет (≈3 года) как стартовое тренировочное окно.
- Двигаемся шагом `step_days` (по умолчанию 10 бизнес-дней).
- На каждом шаге обучаем модель на доступных данных и предсказываем цену P_{t+H}.
- Сравниваем с фактической P_{t+H} (если уже известна).

Метрики на каждом горизонте × модели:
- MAE — средняя абсолютная ошибка цены (USD/lb).
- RMSE — корень среднеквадратичной ошибки.
- MAPE — средняя процентная ошибка.
- Hit rate — доля случаев, когда направление (рост/падение) угадано.
- Coverage@80 — доля случаев, когда фактическая цена попала в [p10, p90].
"""
from __future__ import annotations

import logging
import math
import warnings
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from models import (
    HORIZONS, HorizonForecast,
    forecast_gbm, forecast_arima, forecast_xgboost, forecast_mlp,
    XGBHorizonModel, MLPHorizonModel, ensemble_forecast,
)
from features import prepare_xy, build_features

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


def _evaluate_horizon(actuals: pd.Series, preds: pd.DataFrame) -> Dict[str, float]:
    """preds: DataFrame с колонками point, p10, p90 и индексом, совпадающим с actuals."""
    df = pd.DataFrame({"actual": actuals}).join(preds, how="inner").dropna()
    if df.empty:
        return {"n": 0}
    err = df["actual"] - df["point"]
    mae = float(err.abs().mean())
    rmse = float(np.sqrt((err ** 2).mean()))
    mape = float((err.abs() / df["actual"]).mean() * 100)
    # Направление: сравниваем по логдоходности относительно P0
    p0 = df["p0"]
    actual_up = (df["actual"] > p0).astype(int)
    pred_up = (df["point"] > p0).astype(int)
    hit = float((actual_up == pred_up).mean() * 100)
    coverage = float(((df["actual"] >= df["p10"]) & (df["actual"] <= df["p90"])).mean() * 100)
    return {
        "n": len(df),
        "MAE": mae,
        "RMSE": rmse,
        "MAPE_%": mape,
        "HitRate_%": hit,
        "Coverage80_%": coverage,
    }


def walk_forward(raw_df: pd.DataFrame,
                 train_min_days: int = 750,   # ~3 года бизнес-дней
                 step_days: int = 10,
                 horizons: Optional[List[Dict]] = None,
                 include_xgb: bool = True,
                 include_mlp: bool = False,   # MLP по умолчанию выключен (медленный + переобучается)
                 include_arima: bool = True,
                 include_gbm: bool = True,
                 verbose: bool = True) -> Dict[str, pd.DataFrame]:
    """
    Возвращает {model_name: DataFrame с метриками по каждому горизонту}.
    Дополнительно — детальные прогнозы доступны через результат.
    """
    if horizons is None:
        horizons = HORIZONS
    prices = raw_df["copper"]
    n = len(raw_df)

    # На каждом шаге t (индекс точки прогноза) для каждого горизонта H
    # имеем фактическую цену в t+H. Это сильно ограничивает диапазон точек.
    max_H = max(h["days"] for h in horizons)
    if train_min_days + max_H >= n:
        raise ValueError(f"Недостаточно данных: нужно > {train_min_days + max_H}, есть {n}")

    # Точки прогноза: с train_min_days до n - max_H, шагом step_days
    forecast_indices = list(range(train_min_days, n - max_H, step_days))
    if verbose:
        logger.info("Walk-forward: %d прогнозных точек, %d горизонтов", len(forecast_indices), len(horizons))

    # Накопители прогнозов: predictions[(model, H)] -> list of dict
    predictions: Dict[tuple, List[dict]] = {}

    # Для ускорения предрасчитаем features 1 раз (X_now будет нарезаться)
    features_all = build_features(raw_df)
    features_all = features_all.drop(columns=[c for c in ["log_price"] if c in features_all.columns])

    for step_i, t in enumerate(forecast_indices):
        prices_t = prices.iloc[: t + 1]   # включая текущую точку
        p0 = float(prices_t.iloc[-1])
        date_t = prices_t.index[-1]

        # Цены на горизонтах вперёд (для метрик)
        actuals = {h["days"]: float(prices.iloc[t + h["days"]]) for h in horizons}

        for h in horizons:
            H = h["days"]
            # GBM
            if include_gbm:
                try:
                    fc = forecast_gbm(prices_t, H)
                    predictions.setdefault(("GBM", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                    })
                except Exception as exc:
                    logger.warning("GBM t=%s H=%d failed: %s", date_t, H, exc)
            # ARIMA
            if include_arima:
                try:
                    fc = forecast_arima(prices_t, H)
                    predictions.setdefault(("ARIMA", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                    })
                except Exception as exc:
                    logger.warning("ARIMA t=%s H=%d failed: %s", date_t, H, exc)
            # XGBoost / MLP — обучаем на данных до t (включительно)
            X = y = x_now = None
            if include_xgb or include_mlp:
                try:
                    sub_raw = raw_df.iloc[: t + 1]
                    X, y = prepare_xy(sub_raw, H)
                    if len(X) < 200:
                        X = y = None
                    else:
                        x_now = features_all.loc[[date_t]].reindex(columns=list(X.columns))
                except Exception as exc:
                    logger.warning("X/y t=%s H=%d failed: %s", date_t, H, exc)
                    X = y = x_now = None

            if include_xgb and X is not None:
                try:
                    fc, _ = forecast_xgboost(prices_t, X, y, x_now, H)
                    predictions.setdefault(("XGBoost", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                    })
                except Exception as exc:
                    logger.warning("XGB t=%s H=%d failed: %s", date_t, H, exc)

            if include_mlp and X is not None:
                try:
                    fc, _ = forecast_mlp(prices_t, X, y, x_now, H)
                    predictions.setdefault(("MLP", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                    })
                except Exception as exc:
                    logger.warning("MLP t=%s H=%d failed: %s", date_t, H, exc)

        if verbose and (step_i + 1) % 10 == 0:
            logger.info("  → пройдено %d/%d точек", step_i + 1, len(forecast_indices))

    # Считаем ансамбль: для каждого (H, date) усредняем доступные модели
    # Делаем по сводным DataFrame
    by_model_h: Dict[str, Dict[int, pd.DataFrame]] = {}
    for (mname, H), rows in predictions.items():
        df_m = pd.DataFrame(rows).set_index("date")
        by_model_h.setdefault(mname, {})[H] = df_m

    # Ансамбль (взвешенное среднее доступных моделей)
    ensemble_by_h: Dict[int, pd.DataFrame] = {}
    for H in {H for (_, H) in predictions.keys()}:
        parts = []
        for m in ["XGBoost", "MLP", "ARIMA", "GBM"]:
            if m in by_model_h and H in by_model_h[m]:
                parts.append(by_model_h[m][H][["point", "p10", "p90"]]
                             .add_prefix(f"{m}_"))
        if len(parts) < 2:
            continue
        wide = pd.concat(parts, axis=1)
        actual = by_model_h[list(by_model_h.keys())[0]][H][["p0", "actual"]]
        wide = wide.join(actual, how="inner").dropna()
        weights = {"XGBoost": 0.4, "MLP": 0.2, "ARIMA": 0.25, "GBM": 0.15}
        present = [m for m in ["XGBoost", "MLP", "ARIMA", "GBM"]
                   if f"{m}_point" in wide.columns]
        total_w = sum(weights[m] for m in present)
        wide["point"] = sum(weights[m] * wide[f"{m}_point"] for m in present) / total_w
        wide["p10"] = sum(weights[m] * wide[f"{m}_p10"] for m in present) / total_w
        wide["p90"] = sum(weights[m] * wide[f"{m}_p90"] for m in present) / total_w
        ensemble_by_h[H] = wide[["p0", "actual", "point", "p10", "p90"]]
    if ensemble_by_h:
        by_model_h["Ensemble"] = ensemble_by_h

    # Метрики
    metrics_rows = []
    label_map = {h["days"]: h["label"] for h in horizons}
    for mname, by_h in by_model_h.items():
        for H, dfp in by_h.items():
            m = _evaluate_horizon(dfp["actual"], dfp[["p0", "point", "p10", "p90"]])
            metrics_rows.append({"Модель": mname, "Горизонт": label_map.get(H, H),
                                 "Дней": H, **m})
    metrics_df = pd.DataFrame(metrics_rows).sort_values(["Дней", "Модель"]).reset_index(drop=True)

    return {
        "metrics": metrics_df,
        "predictions": by_model_h,
    }


def summarize_metrics(metrics_df: pd.DataFrame) -> str:
    """Печатная сводка."""
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    return metrics_df.round(4).to_string(index=False)


if __name__ == "__main__":
    import datetime as dt
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from data_loader import load_all

    start = (dt.date.today() - dt.timedelta(days=5 * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)

    # На MVP — большой шаг, чтобы быстро отгонять
    result = walk_forward(raw, train_min_days=600, step_days=20)
    print("\n=== Метрики back-test ===")
    print(summarize_metrics(result["metrics"]))
