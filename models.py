"""
models.py — модели прогноза цены меди на горизонты 3д / 10д / 1м / 3м / 6м.

Архитектура — direct multi-step forecasting: для каждого горизонта отдельная модель,
которая предсказывает лог-доходность за H дней:
    y_h = log(P_{t+H}) - log(P_t)

Затем точечный прогноз:
    P_hat_{t+H} = P_t * exp(y_hat_h)

Реализованы три подхода:
1. GBM (Geometric Brownian Motion) — статистический бенчмарк (drift+sigma из истории).
2. ARIMA — классический бенчмарк временных рядов (на лог-ценах).
3. XGBoost — основная ML-модель на построенных фичах.
4. Ensemble — взвешенное среднее точечных прогнозов (по умолчанию 0.5*XGB + 0.3*ARIMA + 0.2*GBM).

Для каждой модели возвращается:
    - point: точечный прогноз цены P_{t+H}
    - p10, p25, p75, p90: вероятностные коридоры
    - sigma_T: оценка волатильности на горизонте (для квантилей)

Все доходности логарифмические, чтобы сохранять линейность и легко строить квантили.
"""
from __future__ import annotations

import math
import logging
import warnings
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Подавим спам предупреждений ARIMA
warnings.filterwarnings("ignore", category=UserWarning)
warnings.filterwarnings("ignore", category=FutureWarning)


# Сверхкороткие горизонты h_today/h_tomorrow считаются от ПОСЛЕДНЕГО известного
# дневного закрытия: утром это закрытие предыдущего дня, поэтому «закрытие
# сегодня» = +1 торговый день (days=1), «закрытие завтра» = +2 (days=2).
# Берём именно 1 и 2, а не 0: при горизонте 0 цель обучения вырождается в ноль.
HORIZONS: List[Dict] = [
    {"key": "h_today",    "label": "Сегодня",   "days": 1},
    {"key": "h_tomorrow", "label": "Завтра",    "days": 2},
    {"key": "h_3d",  "label": "3 дня",     "days": 3},
    {"key": "h_10d", "label": "10 дней",   "days": 10},
    {"key": "h_1m",  "label": "1 месяц",   "days": 21},
    {"key": "h_3m",  "label": "3 месяца",  "days": 63},
    {"key": "h_6m",  "label": "6 месяцев", "days": 126},
]

# На сверхкоротких горизонтах (1–2 дня) направленный ML по тех-фичам/COT —
# по сути шум: цена за день почти случайна. Для таких горизонтов опираемся
# на статистические модели (GBM + ARIMA: случайное блуждание с малым дрейфом
# и дневной волатильностью), а XGBoost/MLP не задействуем — иначе они дают
# неправдоподобно резкие прогнозы «на завтра».
ML_MIN_HORIZON_DAYS = 3


# ---------- Утилиты для квантилей ----------

def _norm_ppf(p: float) -> float:
    """Обратная функция нормального распределения (Acklam approximation)."""
    a = [-3.969683028665376e+01,  2.209460984245205e+02,
         -2.759285104469687e+02,  1.383577518672690e+02,
         -3.066479806614716e+01,  2.506628277459239e+00]
    b = [-5.447609879822406e+01,  1.615858368580409e+02,
         -1.556989798598866e+02,  6.680131188771972e+01,
         -1.328068155288572e+01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01,
         -2.400758277161838e+00, -2.549732539343734e+00,
          4.374664141464968e+00,  2.938163982698783e+00]
    d = [ 7.784695709041462e-03,  3.224671290700398e-01,
          2.445134137142996e+00,  3.754408661907416e+00]
    pl, ph = 0.02425, 1 - 0.02425
    if p < pl:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    elif p <= ph:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5]) * q / \
               (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    else:
        q = math.sqrt(-2 * math.log(1 - p))
        return -((((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5])) / \
               ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def _norm_cdf(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


@dataclass
class HorizonForecast:
    label: str
    days: int
    model: str
    p0: float
    point: float
    median: float
    p10: float
    p25: float
    p75: float
    p90: float
    mu_T: float
    sigma_T: float

    @property
    def change_pct(self) -> float:
        return (self.point - self.p0) / self.p0 * 100

    @property
    def prob_up(self) -> float:
        if self.sigma_T <= 0:
            return 0.5
        # P(log P_T > log p0) при N(mu_T, sigma_T^2)
        z = self.mu_T / self.sigma_T
        return float(_norm_cdf(z))

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["change_pct"] = self.change_pct
        d["prob_up"] = self.prob_up
        return d


def _quantiles(p0: float, mu_T: float, sigma_T: float) -> Dict[str, float]:
    """Квантили log-нормального распределения вокруг точечного прогноза."""
    return {
        "p10": p0 * math.exp(mu_T + sigma_T * _norm_ppf(0.10)),
        "p25": p0 * math.exp(mu_T + sigma_T * _norm_ppf(0.25)),
        "p75": p0 * math.exp(mu_T + sigma_T * _norm_ppf(0.75)),
        "p90": p0 * math.exp(mu_T + sigma_T * _norm_ppf(0.90)),
        "median": p0 * math.exp(mu_T),
    }


# ---------- Историческая волатильность ----------

def daily_volatility(prices: pd.Series, window: int = 60) -> float:
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return float(log_ret.tail(window).std())


def garch11_volatility(prices: pd.Series, horizon_days: int = 1) -> Tuple[float, dict]:
    """GARCH(1,1) условная волатильность на h дней вперёд.

    Модель: σ²_t = ω + α·ε²_{t-1} + β·σ²_{t-1},  α + β < 1.

    Возвращает (σ_h, params):
      σ_h     — оценка волатильности на h дней (стандартное отклонение лог-дох.)
      params  — {'omega', 'alpha', 'beta', 'persistence', 'long_run_sigma'}

    Если оптимизация не сходится — fallback на простой rolling std.
    """
    from scipy.optimize import minimize

    ret = np.log(prices / prices.shift(1)).dropna().values
    n = len(ret)
    if n < 60:
        return float(np.std(ret) * np.sqrt(horizon_days)), {}

    def _neg_log_likelihood(theta):
        omega, alpha, beta = theta
        if omega <= 0 or alpha < 0 or beta < 0 or (alpha + beta) >= 0.999:
            return 1e10
        sigma2 = np.zeros(n)
        sigma2[0] = np.var(ret)
        for t in range(1, n):
            sigma2[t] = omega + alpha * ret[t-1] ** 2 + beta * sigma2[t-1]
        # log-likelihood без константы
        ll = -0.5 * np.sum(np.log(sigma2) + ret ** 2 / sigma2)
        return -ll

    # Стартовые значения
    var0 = np.var(ret)
    x0 = [var0 * 0.05, 0.05, 0.9]
    try:
        res = minimize(_neg_log_likelihood, x0, method="L-BFGS-B",
                        bounds=[(1e-8, None), (0, 0.5), (0.5, 0.999)],
                        options={"maxiter": 100})
        if not res.success:
            raise RuntimeError("GARCH not converged")
        omega, alpha, beta = res.x
    except Exception:
        return float(np.std(ret[-60:]) * np.sqrt(horizon_days)), {}

    # Восстанавливаем последнюю σ²_t
    sigma2 = np.zeros(n)
    sigma2[0] = var0
    for t in range(1, n):
        sigma2[t] = omega + alpha * ret[t-1] ** 2 + beta * sigma2[t-1]
    sigma2_now = sigma2[-1]

    # Прогноз на h шагов вперёд:
    # E[σ²_{t+h}] → long-run-variance при h→∞, иначе постепенный переход
    long_run_var = omega / max(1 - alpha - beta, 1e-6)
    sigma2_h_total = 0.0
    sigma2_t = sigma2_now
    for _ in range(horizon_days):
        # рекурсивный прогноз дисперсии
        sigma2_t = omega + (alpha + beta) * sigma2_t
        sigma2_h_total += sigma2_t
    # Итоговое σ для накопленной h-дневной доходности:
    sigma_h = float(np.sqrt(sigma2_h_total))

    return sigma_h, {
        "omega": float(omega),
        "alpha": float(alpha),
        "beta": float(beta),
        "persistence": float(alpha + beta),
        "long_run_sigma": float(np.sqrt(long_run_var)),
        "current_sigma": float(np.sqrt(sigma2_now)),
    }


def daily_drift(prices: pd.Series, window: int = 60) -> float:
    log_ret = np.log(prices / prices.shift(1)).dropna()
    return float(log_ret.tail(window).mean()) if len(log_ret) else 0.0


# ---------- Модель 1: GBM ----------

def forecast_gbm(prices: pd.Series, horizon_days: int,
                 vol_window: int = 60, drift_window: int = 60,
                 drift_shrink: float = 0.5,
                 use_garch: bool = True) -> HorizonForecast:
    """Geometric Brownian Motion baseline.
    Точечный прогноз = E[P_T] = P_0 * exp(mu_T + 0.5 * sigma_T^2).
    drift_shrink: коэффициент усадки исторического дрифта к нулю.
    use_garch: использовать GARCH(1,1) условную волатильность вместо
               простого rolling std. По умолчанию True.
    """
    p0 = float(prices.iloc[-1])
    mu_d = daily_drift(prices, drift_window) * drift_shrink
    mu_T = mu_d * horizon_days
    if use_garch:
        try:
            sigma_T, _ = garch11_volatility(prices, horizon_days)
        except Exception:
            sigma_T = daily_volatility(prices, vol_window) * math.sqrt(horizon_days)
    else:
        sigma_T = daily_volatility(prices, vol_window) * math.sqrt(horizon_days)
    q = _quantiles(p0, mu_T, sigma_T)
    return HorizonForecast(
        label=str(horizon_days), days=horizon_days, model="GBM",
        p0=p0,
        point=p0 * math.exp(mu_T + 0.5 * sigma_T ** 2),
        median=q["median"], p10=q["p10"], p25=q["p25"],
        p75=q["p75"], p90=q["p90"],
        mu_T=mu_T, sigma_T=sigma_T,
    )


# ---------- Модель 2: ARIMA ----------

def forecast_arima(prices: pd.Series, horizon_days: int,
                   order: Tuple[int, int, int] = (1, 1, 1),
                   train_window: int = 750) -> HorizonForecast:
    """ARIMA(p,d,q) на логе цены. Для MVP — фиксированный порядок (1,1,1)."""
    from statsmodels.tsa.arima.model import ARIMA

    log_p = np.log(prices.tail(train_window).dropna())
    p0 = float(prices.iloc[-1])

    try:
        model = ARIMA(log_p, order=order, enforce_stationarity=False,
                      enforce_invertibility=False)
        fit = model.fit(method_kwargs={"warn_convergence": False})
        forecast = fit.get_forecast(steps=horizon_days)
        mean_log = float(forecast.predicted_mean.iloc[-1])
        # ARIMA возвращает стандартную ошибку прогноза
        se = float(forecast.se_mean.iloc[-1])
        point = math.exp(mean_log)
        mu_T = mean_log - math.log(p0)
        sigma_T = max(se, 1e-9)
    except Exception as exc:
        logger.warning("ARIMA failed (%s) → fallback to GBM-like estimate", exc)
        sigma_d = daily_volatility(prices, 60)
        mu_d = daily_drift(prices, 60) * 0.5
        mu_T = mu_d * horizon_days
        sigma_T = sigma_d * math.sqrt(horizon_days)
        point = p0 * math.exp(mu_T)

    q = _quantiles(p0, mu_T, sigma_T)
    return HorizonForecast(
        label=str(horizon_days), days=horizon_days, model="ARIMA",
        p0=p0, point=point,
        median=q["median"], p10=q["p10"], p25=q["p25"],
        p75=q["p75"], p90=q["p90"],
        mu_T=mu_T, sigma_T=sigma_T,
    )


# ---------- Модель 3: XGBoost ----------

class XGBHorizonModel:
    """XGBoost-регрессия лог-доходности на горизонт. Direct multi-step.
    Используется с одной парой (X, y) на каждый горизонт.
    """

    def __init__(self, **xgb_params):
        from xgboost import XGBRegressor
        defaults = dict(
            n_estimators=400,
            max_depth=4,
            learning_rate=0.03,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            min_child_weight=5,
            tree_method="hist",
            random_state=42,
            verbosity=0,
        )
        defaults.update(xgb_params)
        self.model = XGBRegressor(**defaults)
        self.feature_names_: Optional[List[str]] = None
        self.residual_std_: Optional[float] = None

    def fit(self, X: pd.DataFrame, y: pd.Series, val_frac: float = 0.15):
        """Обучение с holdout-валидацией (хвост) для оценки шума остатков."""
        n = len(X)
        n_val = max(20, int(n * val_frac))
        X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]
        y_train, y_val = y.iloc[:-n_val], y.iloc[-n_val:]
        self.model.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)
        self.feature_names_ = list(X.columns)
        # Std остатков на валидации — основа для квантилей
        pred_val = self.model.predict(X_val)
        resid = y_val.values - pred_val
        self.residual_std_ = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
        return self

    def predict(self, x_now: pd.DataFrame) -> float:
        return float(self.model.predict(x_now[self.feature_names_])[0])

    def conformal_quantiles(self, X_val: pd.DataFrame, y_val: pd.Series,
                              alphas=(0.10, 0.25, 0.75, 0.90)) -> Dict[float, float]:
        """Split-conformal: эмпирические квантили остатков на validation.
        Применяются как смещение к точечному прогнозу:
          q_α = mu + r_α, где r_α — α-квантиль остатков y_val - pred_val.
        Это даёт калиброванные интервалы без normality-assumption.
        """
        pred = self.model.predict(X_val[self.feature_names_])
        resid = y_val.values - pred
        return {a: float(np.quantile(resid, a)) for a in alphas}


    def explain(self, x_now: pd.DataFrame, top_n: int = 10):
        """SHAP-style объяснение через встроенный pred_contribs XGBoost.
        Не требует библиотеки shap.

        Возвращает DataFrame:
          feature | value | contribution | abs_contrib
        Отсортирован по |contribution| убыванию, top_n строк.
        + dict с 'baseline' (bias) и 'prediction' (сумма всех contribs).
        """
        import xgboost as xgb
        x_aligned = x_now[self.feature_names_]
        # Используем Booster.predict напрямую — нужно DMatrix
        dmat = xgb.DMatrix(x_aligned.values, feature_names=self.feature_names_)
        contribs = self.model.get_booster().predict(dmat, pred_contribs=True)
        # contribs shape: (n_samples, n_features + 1), последний столбец = baseline
        row = contribs[0]
        baseline = float(row[-1])
        feat_contribs = row[:-1]

        df = pd.DataFrame({
            "feature": self.feature_names_,
            "value": x_aligned.iloc[0].values,
            "contribution": feat_contribs,
        })
        df["abs_contrib"] = df["contribution"].abs()
        df = df.sort_values("abs_contrib", ascending=False).head(top_n).reset_index(drop=True)

        return df, {
            "baseline": baseline,
            "prediction": baseline + float(feat_contribs.sum()),
            "total_features": len(self.feature_names_),
        }


class XGBQuantileModel:
    """Отдельные XGBoost-модели для квантилей p10/p25/p75/p90.
    Использует objective='reg:quantileerror' (требует XGBoost >= 2.0).
    Это даёт **асимметричные** коридоры — лучше для скошенных распределений.
    """
    QUANTILES = [0.10, 0.25, 0.75, 0.90]

    def __init__(self, **xgb_params):
        from xgboost import XGBRegressor
        self.models: Dict[float, "XGBRegressor"] = {}
        self.feature_names_: Optional[List[str]] = None
        self.xgb_params = dict(
            n_estimators=200,
            max_depth=4,
            learning_rate=0.04,
            subsample=0.8,
            colsample_bytree=0.8,
            reg_lambda=1.0,
            min_child_weight=5,
            tree_method="hist",
            random_state=42,
            verbosity=0,
        )
        self.xgb_params.update(xgb_params)

    def fit(self, X: pd.DataFrame, y: pd.Series):
        from xgboost import XGBRegressor
        self.feature_names_ = list(X.columns)
        for q in self.QUANTILES:
            m = XGBRegressor(
                objective="reg:quantileerror",
                quantile_alpha=q,
                **self.xgb_params,
            )
            m.fit(X, y, verbose=False)
            self.models[q] = m
        return self

    def predict_quantiles(self, x_now: pd.DataFrame) -> Dict[float, float]:
        return {q: float(m.predict(x_now[self.feature_names_])[0])
                for q, m in self.models.items()}


def forecast_xgboost_quantile(prices: pd.Series,
                                X_train: pd.DataFrame, y_train: pd.Series,
                                X_now: pd.DataFrame,
                                horizon_days: int) -> HorizonForecast:
    """XGBoost с reg:quantileerror — отдельная модель для каждого квантиля.
    Даёт асимметричный коридор p10-p90. Точечный = средний квантиль.
    """
    p0 = float(prices.iloc[-1])
    model = XGBQuantileModel().fit(X_train, y_train)
    q = model.predict_quantiles(X_now)
    # Точечный — между p25 и p75
    mu_T = 0.5 * (q[0.25] + q[0.75])
    sigma_d = daily_volatility(prices, 60)
    floor_sigma = sigma_d * math.sqrt(horizon_days)
    # σ из квантилей: p90 - p10 ≈ 2.56 σ для нормали
    width = q[0.90] - q[0.10]
    sigma_T = max(width / 2.56, floor_sigma, 1e-9)
    point = p0 * math.exp(mu_T)
    return HorizonForecast(
        label=str(horizon_days), days=horizon_days, model="XGBQuantile",
        p0=p0, point=point,
        median=point,
        p10=p0 * math.exp(q[0.10]),
        p25=p0 * math.exp(q[0.25]),
        p75=p0 * math.exp(q[0.75]),
        p90=p0 * math.exp(q[0.90]),
        mu_T=mu_T, sigma_T=sigma_T,
    )


def forecast_xgboost(prices: pd.Series,
                     X_train: pd.DataFrame, y_train: pd.Series,
                     X_now: pd.DataFrame,
                     horizon_days: int,
                     model: Optional[XGBHorizonModel] = None) -> Tuple[HorizonForecast, XGBHorizonModel]:
    """Обучает XGB и возвращает прогноз. Если model передан — переиспользует обученный.
    σ_T = max(std остатков на валидации, историческая σ_d * √H) — защита от
    занижения коридора при коротких validation-выборках.
    """
    p0 = float(prices.iloc[-1])
    if model is None:
        model = XGBHorizonModel().fit(X_train, y_train)

    mu_T = model.predict(X_now)
    sigma_d = daily_volatility(prices, 60)
    floor_sigma = sigma_d * math.sqrt(horizon_days)
    sigma_T = max(model.residual_std_ or 0.0, floor_sigma, 1e-9)

    # Без log-normal коррекции — она симметрии и без того в exp() заложена.
    point = p0 * math.exp(mu_T)
    q = _quantiles(p0, mu_T, sigma_T)
    return HorizonForecast(
        label=str(horizon_days), days=horizon_days, model="XGBoost",
        p0=p0, point=point,
        median=q["median"], p10=q["p10"], p25=q["p25"],
        p75=q["p75"], p90=q["p90"],
        mu_T=mu_T, sigma_T=sigma_T,
    ), model


# ---------- Модель 4: MLP (sklearn) ----------

class MLPHorizonModel:
    """MLPRegressor через sklearn (без torch/TF).
    Standard-scaling X на train, ранний стоп через validation_fraction.
    """

    def __init__(self, hidden_layer_sizes=(24, 12), max_iter: int = 500,
                 random_state: int = 42, alpha: float = 5e-2, **kwargs):
        from sklearn.neural_network import MLPRegressor
        from sklearn.preprocessing import StandardScaler
        from sklearn.pipeline import Pipeline
        self.pipe = Pipeline([
            ("scaler", StandardScaler()),
            ("mlp", MLPRegressor(
                hidden_layer_sizes=hidden_layer_sizes,
                max_iter=max_iter,
                early_stopping=True,
                validation_fraction=0.15,
                n_iter_no_change=20,
                random_state=random_state,
                alpha=alpha,
                learning_rate_init=5e-4,
                solver="adam",
                **kwargs,
            )),
        ])
        self.feature_names_: Optional[List[str]] = None
        self.residual_std_: Optional[float] = None

    def fit(self, X: pd.DataFrame, y: pd.Series, val_frac: float = 0.15):
        n = len(X)
        n_val = max(20, int(n * val_frac))
        X_train, X_val = X.iloc[:-n_val], X.iloc[-n_val:]
        y_train, y_val = y.iloc[:-n_val], y.iloc[-n_val:]
        self.pipe.fit(X_train, y_train)
        self.feature_names_ = list(X.columns)
        pred_val = self.pipe.predict(X_val)
        resid = y_val.values - pred_val
        self.residual_std_ = float(np.std(resid, ddof=1)) if len(resid) > 1 else 0.0
        return self

    def predict(self, x_now: pd.DataFrame) -> float:
        return float(self.pipe.predict(x_now[self.feature_names_])[0])


def forecast_mlp(prices: pd.Series,
                 X_train: pd.DataFrame, y_train: pd.Series,
                 X_now: pd.DataFrame,
                 horizon_days: int,
                 model: Optional[MLPHorizonModel] = None) -> Tuple[HorizonForecast, MLPHorizonModel]:
    """MLP-прогноз. По структуре идентичен XGB-forecast.
    μ_T клиппится в пределах ±3·hist_vol·√H — защита от экстремальных выбросов
    переобученной сети.
    """
    p0 = float(prices.iloc[-1])
    if model is None:
        model = MLPHorizonModel().fit(X_train, y_train)
    mu_T_raw = model.predict(X_now)
    sigma_d = daily_volatility(prices, 60)
    floor_sigma = sigma_d * math.sqrt(horizon_days)
    # Клипп μ в пределах ±3·σ горизонта — никакой ML-модели нельзя верить дальше
    cap = 3 * floor_sigma
    mu_T = float(np.clip(mu_T_raw, -cap, cap))
    sigma_T = max(model.residual_std_ or 0.0, floor_sigma, 1e-9)
    # Если residual_std сильно превышает hist-vol — сеть нестабильна, режем
    sigma_T = min(sigma_T, 2.5 * floor_sigma)
    point = p0 * math.exp(mu_T)
    q = _quantiles(p0, mu_T, sigma_T)
    return HorizonForecast(
        label=str(horizon_days), days=horizon_days, model="MLP",
        p0=p0, point=point,
        median=q["median"], p10=q["p10"], p25=q["p25"],
        p75=q["p75"], p90=q["p90"],
        mu_T=mu_T, sigma_T=sigma_T,
    ), model


# ---------- Ансамбль ----------

DEFAULT_WEIGHTS = {"XGBoost": 0.4, "MLP": 0.2, "ARIMA": 0.25, "GBM": 0.15}

# Адаптивные веса по режиму: в Calm доверяем ML, в Turbulent — консервативно
ADAPTIVE_WEIGHTS = {
    "calm":      {"XGBoost": 0.45, "MLP": 0.25, "ARIMA": 0.20, "GBM": 0.10},
    "turbulent": {"XGBoost": 0.15, "MLP": 0.10, "ARIMA": 0.35, "GBM": 0.40},
}


def adaptive_weights_from_regime(calm_prob: float) -> Dict[str, float]:
    """Линейная интерполяция весов между Calm и Turbulent по вероятности.

    calm_prob = 0.0 → полный Turbulent
    calm_prob = 1.0 → полный Calm
    Промежуточные значения — линейное смешение, нормированное к сумме 1.
    """
    cw = ADAPTIVE_WEIGHTS["calm"]
    tw = ADAPTIVE_WEIGHTS["turbulent"]
    a = max(0.0, min(1.0, float(calm_prob)))
    out = {k: a * cw[k] + (1 - a) * tw[k] for k in cw}
    s = sum(out.values())
    return {k: v / s for k, v in out.items()}


def ensemble_forecast(forecasts: Dict[str, HorizonForecast],
                      weights: Optional[Dict[str, float]] = None) -> HorizonForecast:
    """Взвешенный ансамбль: усредняем mu_T (в лог-пространстве) и берём максимум sigma_T
    из участников, чтобы коридор не был занижен.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS
    items = [(name, f) for name, f in forecasts.items() if name in weights]
    if not items:
        raise ValueError("Пусто: нет ни одной модели для ансамбля")
    p0 = items[0][1].p0
    H = items[0][1].days
    total_w = sum(weights[name] for name, _ in items)
    mu_T = sum(weights[name] * f.mu_T for name, f in items) / total_w
    # Sigma — среднее, не максимум, чтобы не раздувать коридор
    sigma_T = sum(weights[name] * f.sigma_T for name, f in items) / total_w
    q = _quantiles(p0, mu_T, sigma_T)
    return HorizonForecast(
        label=items[0][1].label, days=H, model="Ensemble",
        p0=p0,
        point=p0 * math.exp(mu_T + 0.5 * sigma_T ** 2),
        median=q["median"], p10=q["p10"], p25=q["p25"],
        p75=q["p75"], p90=q["p90"],
        mu_T=mu_T, sigma_T=sigma_T,
    )


# ---------- Главная точка входа ----------

def forecast_all_horizons(raw_df: pd.DataFrame,
                          use_xgb: bool = True,
                          use_mlp: bool = True,
                          use_arima: bool = True,
                          use_gbm: bool = True,
                          xgb_models_out: Optional[Dict] = None,
                          xgb_x_now_out: Optional[Dict] = None) -> Dict[str, Dict[str, HorizonForecast]]:
    """Возвращает {horizon_key: {model_name: HorizonForecast}}.
    raw_df — результат data_loader.load_all().

    Если переданы xgb_models_out и xgb_x_now_out — в них пишутся обученные
    XGBoost-модели для каждого горизонта (для SHAP-объяснений).
    """
    from features import prepare_xy, build_features

    prices = raw_df["copper"]
    results: Dict[str, Dict[str, HorizonForecast]] = {}

    # Заранее построим фичи на все строки для X_now (БЕЗ dropna — иначе
    # выкашиваются ряды с локальными NaN и теряется последняя строка)
    features_all = build_features(raw_df)
    x_now = features_all.drop(columns=[c for c in ["log_price"] if c in features_all.columns])
    # Последняя строка с не-NaN копперт (последняя торговая дата)
    x_now = x_now.iloc[[-1]]

    for h in HORIZONS:
        H = h["days"]
        horizon_results: Dict[str, HorizonForecast] = {}

        # Сверхкороткие горизонты: ML глушим, оставляем GBM+ARIMA (см. ML_MIN_HORIZON_DAYS)
        h_use_xgb = use_xgb and H >= ML_MIN_HORIZON_DAYS
        h_use_mlp = use_mlp and H >= ML_MIN_HORIZON_DAYS

        if use_gbm:
            try:
                horizon_results["GBM"] = forecast_gbm(prices, H)
            except Exception as exc:
                logger.warning("GBM h=%d failed: %s", H, exc)

        if use_arima:
            try:
                horizon_results["ARIMA"] = forecast_arima(prices, H)
            except Exception as exc:
                logger.warning("ARIMA h=%d failed: %s", H, exc)

        # Подготовка X/y для ML-моделей — один раз на горизонт
        X = y = x_now_aligned = None
        if h_use_xgb or h_use_mlp:
            try:
                X, y = prepare_xy(raw_df, H)
                cols = list(X.columns)
                x_now_aligned = x_now.reindex(columns=cols)
            except Exception as exc:
                logger.warning("Не удалось собрать X/y для h=%d: %s", H, exc)

        if h_use_xgb and X is not None:
            try:
                fc, xgb_model = forecast_xgboost(prices, X, y, x_now_aligned, H)
                horizon_results["XGBoost"] = fc
                if xgb_models_out is not None:
                    xgb_models_out[h["key"]] = xgb_model
                if xgb_x_now_out is not None:
                    xgb_x_now_out[h["key"]] = x_now_aligned
            except Exception as exc:
                logger.warning("XGBoost h=%d failed: %s", H, exc)

        if h_use_mlp and X is not None:
            try:
                fc, _ = forecast_mlp(prices, X, y, x_now_aligned, H)
                horizon_results["MLP"] = fc
            except Exception as exc:
                logger.warning("MLP h=%d failed: %s", H, exc)

        # Ансамбль
        if len(horizon_results) >= 2:
            try:
                horizon_results["Ensemble"] = ensemble_forecast(horizon_results)
            except Exception as exc:
                logger.warning("Ensemble h=%d failed: %s", H, exc)

        results[h["key"]] = horizon_results

    return results


def forecast_at_point(raw_df: pd.DataFrame, as_of_date: pd.Timestamp,
                      use_xgb: bool = True, use_mlp: bool = True,
                      use_arima: bool = True, use_gbm: bool = True,
                      ) -> Dict[str, Dict[str, HorizonForecast]]:
    """Прогноз ИЗ ИСТОРИЧЕСКОЙ ТОЧКИ.
    Использует только данные ДО as_of_date (включительно).
    Возвращает ту же структуру, что forecast_all_horizons.

    Применение: проверка «что бы предсказала модель на дату X».
    """
    if as_of_date not in raw_df.index:
        # Берём ближайшую доступную дату <= as_of_date
        valid = raw_df.index[raw_df.index <= as_of_date]
        if len(valid) == 0:
            raise ValueError(f"Нет данных до {as_of_date}")
        as_of_date = valid.max()

    sub_df = raw_df.loc[:as_of_date].copy()
    return forecast_all_horizons(
        sub_df, use_xgb=use_xgb, use_mlp=use_mlp,
        use_arima=use_arima, use_gbm=use_gbm,
    )


def actuals_after_point(raw_df: pd.DataFrame, as_of_date: pd.Timestamp,
                        horizons_days: List[int] = None) -> Dict[int, float]:
    """Возвращает фактические цены через H дней от as_of_date, если они доступны.
    {H: P_{t+H}} — если t+H выходит за пределы данных, возвращает None.
    """
    if horizons_days is None:
        horizons_days = [h["days"] for h in HORIZONS]
    if as_of_date not in raw_df.index:
        valid = raw_df.index[raw_df.index <= as_of_date]
        if len(valid) == 0:
            return {h: None for h in horizons_days}
        as_of_date = valid.max()

    idx = raw_df.index.get_loc(as_of_date)
    out = {}
    n = len(raw_df)
    for H in horizons_days:
        target_idx = idx + H
        if target_idx < n:
            out[H] = float(raw_df["copper"].iloc[target_idx])
        else:
            out[H] = None
    return out


def forecasts_to_dataframe(results: Dict[str, Dict[str, HorizonForecast]]) -> pd.DataFrame:
    """Плоская таблица для вывода. По строке на (горизонт × модель)."""
    rows = []
    label_map = {h["key"]: h["label"] for h in HORIZONS}
    for hk, models in results.items():
        for mname, f in models.items():
            rows.append({
                "Горизонт": label_map[hk],
                "Дней": f.days,
                "Модель": mname,
                "P0, USD/lb": f.p0,
                "Точечный": f.point,
                "Медиана": f.median,
                "p10": f.p10,
                "p25": f.p25,
                "p75": f.p75,
                "p90": f.p90,
                "Δ, %": f.change_pct,
                "P(↑), %": f.prob_up * 100,
                "σ_T": f.sigma_T,
            })
    return pd.DataFrame(rows)


if __name__ == "__main__":
    import datetime as dt
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    from data_loader import load_all

    start = (dt.date.today() - dt.timedelta(days=5 * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    results = forecast_all_horizons(raw)
    df = forecasts_to_dataframe(results)
    pd.set_option("display.max_columns", None)
    pd.set_option("display.width", 200)
    print(df.round(4).to_string(index=False))
