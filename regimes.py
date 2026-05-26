"""
regimes.py — Markov-switching модель режимов рынка меди.

Цель: выделить 2-3 латентных режима на дневных лог-доходностях меди
(например, low-vol / high-vol; bull / bear / sideways).

Используется:
- `statsmodels.tsa.regime_switching.markov_regression.MarkovRegression`
- Лог-доходности с автокорреляцией порядка 1.
- По умолчанию k_regimes=2 (calm vs turbulent), но можно k_regimes=3.

Выход:
- `RegimeFit.params` — оценённые μ_i, σ_i для каждого режима.
- `RegimeFit.smoothed_probs` — апостериорные вероятности режимов на каждой дате.
- `RegimeFit.current_regime` — индекс наиболее вероятного режима сейчас.
- `RegimeFit.label_map` — человекочитаемые названия ("Calm bull", "Vola correction").

Применение: подавать вероятности в качестве фич, либо использовать для
адаптивного перевзвешивания моделей (например, в risk-off режиме давать
больше веса GBM, в risk-on — XGBoost).
"""
from __future__ import annotations

import logging
import warnings
from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)
warnings.filterwarnings("ignore")


@dataclass
class RegimeFit:
    k_regimes: int
    params: pd.DataFrame              # mu, sigma, persistence для каждого режима
    smoothed_probs: pd.DataFrame      # колонки = режим 0..k-1, индекс = даты
    filtered_probs: pd.DataFrame
    current_regime: int
    current_probs: Dict[int, float]
    label_map: Dict[int, str]
    log_likelihood: float


def _label_regimes(params: pd.DataFrame) -> Dict[int, str]:
    """Простая эвристика: режим с большей σ → 'Turbulent'/'Risk-off';
    режим с положительным μ → 'Bull', отрицательным — 'Bear', около нуля — 'Calm'.
    """
    k = len(params)
    labels: Dict[int, str] = {}
    # Сортируем по σ для разделения calm/turbulent
    sorted_by_sigma = params.sort_values("sigma")
    sigma_low_idx = sorted_by_sigma.index[0]
    sigma_high_idx = sorted_by_sigma.index[-1]

    for idx, row in params.iterrows():
        mu_ann = row["mu"] * 252
        sigma_ann = row["sigma"] * np.sqrt(252)
        if k == 2:
            if idx == sigma_low_idx:
                tag = "Calm" if mu_ann >= 0 else "Sideways"
            else:
                tag = "Turbulent" if mu_ann <= 0 else "Bull-volatile"
        else:
            # 3 режима
            if idx == sigma_low_idx:
                tag = "Calm bull" if mu_ann > 0 else "Calm bear"
            elif idx == sigma_high_idx:
                tag = "Turbulent" if mu_ann <= 0 else "Bull-volatile"
            else:
                tag = "Trending" if mu_ann > 0 else "Correction"
        labels[idx] = f"{tag} (μ={mu_ann*100:+.1f}%, σ={sigma_ann*100:.0f}%)"
    return labels


def fit_markov_regimes(prices: pd.Series, k_regimes: int = 2,
                       order: int = 0, switching_variance: bool = True) -> RegimeFit:
    """
    Обучает MarkovRegression на лог-доходностях меди.
    order: AR-порядок (по умолчанию 0 — чистый switching mean+variance).
    switching_variance: разная σ для каждого режима (рекомендуется True).
    """
    from statsmodels.tsa.regime_switching.markov_regression import MarkovRegression

    log_ret = np.log(prices / prices.shift(1)).dropna()
    model = MarkovRegression(
        log_ret.values,
        k_regimes=k_regimes,
        trend="c",
        switching_variance=switching_variance,
        order=order,
    )
    res = model.fit(disp=False)

    # У MarkovRegression res.params — np.ndarray, имена — в model.param_names
    p_arr = np.asarray(res.params).ravel()
    name_to_val = dict(zip(model.param_names, p_arr.tolist()))

    def _lookup(*keys):
        for k in keys:
            if k in name_to_val:
                return float(name_to_val[k])
        return float("nan")

    params_rows = []
    for k in range(k_regimes):
        mu_k = _lookup(f"const[{k}]", f"intercept[{k}]", f"Intercept[{k}]")
        sigma2_k = _lookup(f"sigma2[{k}]", "sigma2")
        sigma_k = float(np.sqrt(sigma2_k)) if sigma2_k and sigma2_k > 0 else float("nan")
        # Persistence: P(stay)
        try:
            rt = np.asarray(res.regime_transition)
            # Может быть формы (k, k, 1) либо (k, k)
            if rt.ndim == 3:
                p_kk = rt[k, k, 0]
            else:
                p_kk = rt[k, k]
        except Exception:
            p_kk = float("nan")
        params_rows.append({"regime": k, "mu": float(mu_k),
                            "sigma": float(sigma_k),
                            "persistence": float(p_kk)})
    params = pd.DataFrame(params_rows).set_index("regime")

    smoothed = pd.DataFrame(res.smoothed_marginal_probabilities,
                            index=log_ret.index,
                            columns=[f"regime_{k}" for k in range(k_regimes)])
    filtered = pd.DataFrame(res.filtered_marginal_probabilities,
                            index=log_ret.index,
                            columns=[f"regime_{k}" for k in range(k_regimes)])

    current = int(smoothed.iloc[-1].values.argmax())
    current_probs = {k: float(smoothed.iloc[-1, k]) for k in range(k_regimes)}
    labels = _label_regimes(params)

    return RegimeFit(
        k_regimes=k_regimes,
        params=params,
        smoothed_probs=smoothed,
        filtered_probs=filtered,
        current_regime=current,
        current_probs=current_probs,
        label_map=labels,
        log_likelihood=float(res.llf),
    )


def regime_features(fit: RegimeFit, daily_index: pd.DatetimeIndex) -> pd.DataFrame:
    """Превращает smoothed probabilities в фичи на дневной сетке."""
    out = fit.smoothed_probs.reindex(daily_index, method="ffill")
    out.columns = [f"regime_prob_{k}" for k in range(fit.k_regimes)]
    return out


def summarize_fit(fit: RegimeFit) -> str:
    """Текстовая сводка для CLI."""
    lines = ["=== Markov regime fit ==="]
    lines.append(f"k_regimes = {fit.k_regimes}, log-likelihood = {fit.log_likelihood:.2f}")
    lines.append(f"\nПараметры режимов:")
    p = fit.params.copy()
    p["μ_year_%"] = p["mu"] * 252 * 100
    p["σ_year_%"] = p["sigma"] * np.sqrt(252) * 100
    p["P(stay)"] = p["persistence"]
    lines.append(p[["μ_year_%", "σ_year_%", "P(stay)"]].round(2).to_string())
    lines.append(f"\nВероятности текущего режима ({fit.smoothed_probs.index.max().date()}):")
    for k, prob in fit.current_probs.items():
        marker = "  <— TEKУЩИЙ" if k == fit.current_regime else ""
        lines.append(f"  regime {k} {fit.label_map[k]}: {prob*100:.1f}%{marker}")
    return "\n".join(lines)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    import datetime as dt
    from data_loader import load_all

    start = (dt.date.today() - dt.timedelta(days=5 * 365)).strftime("%Y-%m-%d")
    raw = load_all(start=start, include_cot=False, include_lme_stocks=False,
                   include_fred=False)

    for k in [2, 3]:
        print(f"\n############## k_regimes = {k} ##############")
        fit = fit_markov_regimes(raw["copper"], k_regimes=k)
        print(summarize_fit(fit))
