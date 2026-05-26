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
import signal
import warnings
from contextlib import contextmanager
from typing import Dict, List, Optional

import numpy as np
import pandas as pd


# ---------------------------------------------------------------------
#  Таймаут на отдельные операции (защита от зависших ARIMA / др. fit'ов)
# ---------------------------------------------------------------------

class _OpTimeout(Exception):
    """Срабатывает, если операция превысила лимит времени."""


@contextmanager
def _time_limit(seconds: int):
    """Контекст-менеджер с таймаутом на Unix (SIGALRM).
    На Windows таймаут не работает — выдаёт результат как есть.
    Допустимо: Streamlit Cloud работает на Linux.
    """
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handle(signum, frame):
        raise _OpTimeout(f"operation exceeded {seconds}s")

    old_handler = signal.signal(signal.SIGALRM, _handle)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)

from models import (
    HORIZONS, HorizonForecast,
    forecast_gbm, forecast_arima, forecast_xgboost, forecast_mlp,
    XGBHorizonModel, MLPHorizonModel, ensemble_forecast,
    _quantiles, daily_volatility,
)
from features import prepare_xy, build_features, make_target

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
                 verbose: bool = True,
                 progress_callback=None) -> Dict[str, pd.DataFrame]:
    """Walk-forward валидация.

    progress_callback(step, total) — опциональная функция для UI-прогресса
    (например, st.progress в Streamlit).
    """
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

    horizons_days = [h["days"] for h in horizons]
    max_horizon = max(horizons_days)

    # ====================================================================
    # ПРЕДВАРИТЕЛЬНЫЕ ВЫЧИСЛЕНИЯ — выполняются 1 раз, не на каждой точке
    # ====================================================================

    # (1) Фичи — point-in-time, поэтому строим один раз на полной истории
    if verbose:
        logger.info("Pre-compute: features…")
    features_all = build_features(raw_df)
    features_all = features_all.drop(
        columns=[c for c in ["log_price"] if c in features_all.columns]
    )
    # Авто-дроп редких колонок (покрытие <50%) — один раз для всех t
    coverage = features_all.notna().mean()
    sparse_cols = coverage[coverage < 0.5].index.tolist()
    if sparse_cols:
        features_all = features_all.drop(columns=sparse_cols)

    # (2) Таргеты для каждого H — тоже один раз
    if verbose:
        logger.info("Pre-compute: targets for each horizon…")
    targets_by_H = {H: make_target(raw_df, H) for H in horizons_days}

    # ====================================================================
    # ЦИКЛ ПО ТОЧКАМ
    # ====================================================================
    from statsmodels.tsa.arima.model import ARIMA as _ARIMA  # импорт один раз

    for step_i, t in enumerate(forecast_indices):
        prices_t = prices.iloc[: t + 1]   # включая текущую точку
        p0 = float(prices_t.iloc[-1])
        date_t = prices_t.index[-1]
        p0_log = math.log(p0)
        sigma_d = daily_volatility(prices_t, 60)

        # Цены на горизонтах вперёд (для метрик)
        actuals = {H: float(prices.iloc[t + H]) for H in horizons_days}

        # ---------- GBM (быстрый, на каждый H) ----------
        if include_gbm:
            for H in horizons_days:
                try:
                    fc = forecast_gbm(prices_t, H)
                    predictions.setdefault(("GBM", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                    })
                except Exception as exc:
                    logger.warning("GBM t=%s H=%d failed: %s", date_t, H, exc)

        # ---------- ARIMA — ОДИН фит на max_horizon, потом срезы по H ----------
        if include_arima:
            try:
                log_p = np.log(prices_t.tail(750).dropna())
                # Жёсткий таймаут 8 сек: если ARIMA зависнет — переходим к fallback
                with _time_limit(8):
                    fit = _ARIMA(
                        log_p, order=(1, 1, 1),
                        enforce_stationarity=False,
                        enforce_invertibility=False,
                    ).fit(method_kwargs={"warn_convergence": False, "maxiter": 50})
                    forecast = fit.get_forecast(steps=max_horizon)
                    pred_mean = np.asarray(forecast.predicted_mean)
                    se_mean = np.asarray(forecast.se_mean)
                for H in horizons_days:
                    mean_log = float(pred_mean[H - 1])
                    sigma_T = max(float(se_mean[H - 1]), 1e-9)
                    mu_T = mean_log - p0_log
                    point = math.exp(mean_log)
                    q = _quantiles(p0, mu_T, sigma_T)
                    predictions.setdefault(("ARIMA", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": point, "p10": q["p10"], "p90": q["p90"],
                    })
            except (_OpTimeout, Exception) as exc:
                # Fallback: GBM-style для всех H (стандартное случайное блуждание)
                if isinstance(exc, _OpTimeout):
                    logger.warning("ARIMA t=%s: timeout → fallback GBM-style", date_t)
                else:
                    logger.warning("ARIMA t=%s failed (%s) → fallback GBM-style", date_t, exc)
                from models import daily_drift
                mu_d = daily_drift(prices_t, 60) * 0.5
                for H in horizons_days:
                    mu_T = mu_d * H
                    sigma_T = sigma_d * math.sqrt(H)
                    point = p0 * math.exp(mu_T)
                    q = _quantiles(p0, mu_T, sigma_T)
                    predictions.setdefault(("ARIMA", H), []).append({
                        "date": date_t, "p0": p0, "actual": actuals[H],
                        "point": point, "p10": q["p10"], "p90": q["p90"],
                    })

        # ---------- XGBoost / MLP: используем кэшированные features и targets ----------
        if include_xgb or include_mlp:
            # X_full точка t (последняя строка) для predict
            try:
                x_now_full = features_all.loc[[date_t]]
            except KeyError:
                x_now_full = None

            for H in horizons_days:
                if x_now_full is None:
                    continue
                # Срез до текущей точки t (без look-ahead)
                X_slice = features_all.iloc[: t + 1]
                y_slice = targets_by_H[H].iloc[: t + 1]
                data = X_slice.join(y_slice, how="inner").dropna()
                if len(data) < 200:
                    continue
                X = data.drop(columns=[y_slice.name])
                y = data[y_slice.name]
                x_now = x_now_full.reindex(columns=list(X.columns))

                if include_xgb:
                    try:
                        with _time_limit(15):
                            fc, _ = forecast_xgboost(prices_t, X, y, x_now, H)
                        predictions.setdefault(("XGBoost", H), []).append({
                            "date": date_t, "p0": p0, "actual": actuals[H],
                            "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                        })
                    except (_OpTimeout, Exception) as exc:
                        logger.warning("XGB t=%s H=%d failed: %s", date_t, H, exc)

                if include_mlp:
                    try:
                        with _time_limit(15):
                            fc, _ = forecast_mlp(prices_t, X, y, x_now, H)
                        predictions.setdefault(("MLP", H), []).append({
                            "date": date_t, "p0": p0, "actual": actuals[H],
                            "point": fc.point, "p10": fc.p10, "p90": fc.p90,
                        })
                    except (_OpTimeout, Exception) as exc:
                        logger.warning("MLP t=%s H=%d failed: %s", date_t, H, exc)

        if verbose and ((step_i + 1) % 5 == 0 or step_i == 0):
            logger.info("  → %d / %d точек", step_i + 1, len(forecast_indices))
        if progress_callback is not None:
            try:
                progress_callback(step_i + 1, len(forecast_indices))
            except Exception:
                pass

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
