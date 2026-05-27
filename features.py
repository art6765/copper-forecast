"""
features.py — построение фичей для ML-моделей прогноза цены меди.

Что считаем (всё на дневных рядах):
1. Логарифмическая цена и логдоходности.
2. Лаги цены и доходности (1, 2, 3, 5, 10, 20, 60).
3. Скользящие средние и их соотношения (5/20, 20/60).
4. Скользящая волатильность и моментум.
5. RSI(14), MACD(12,26,9), Bollinger %B(20,2).
6. ATR(14) — истинный диапазон, мера волатильности.
7. Кросс-активные признаки: лог-доходности DXY, WTI, gold, silver, sp500, us10y.
8. Календарные: день недели, день месяца, месяц.

Все фичи рассчитаны point-in-time — никакого подсматривания в будущее.
"""
from __future__ import annotations

from typing import List

import numpy as np
import pandas as pd


LAGS_RET = [1, 2, 3, 5, 10, 20, 60]
LAGS_PRICE = [1, 5, 20]
SMA_WINDOWS = [5, 10, 20, 60]
VOL_WINDOWS = [10, 20, 60]
CROSS_ASSETS = ["dxy", "wti", "gold", "silver", "sp500", "us10y"]


def _rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1 / period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - 100 / (1 + rs)


def _macd(series: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9):
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    return macd_line, signal_line, macd_line - signal_line


def _bollinger_pctb(series: pd.Series, window: int = 20, num_std: float = 2.0) -> pd.Series:
    ma = series.rolling(window).mean()
    sd = series.rolling(window).std()
    upper = ma + num_std * sd
    lower = ma - num_std * sd
    return (series - lower) / (upper - lower)


def _atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    prev_close = close.shift(1)
    tr = pd.concat([(high - low),
                    (high - prev_close).abs(),
                    (low - prev_close).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, adjust=False).mean()


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    """Полный pipeline. На входе — dataframe от data_loader.load_all().
    На выходе — DataFrame с фичами (без таргета); индекс — даты.
    """
    out = pd.DataFrame(index=df.index)
    p = df["copper"]
    log_p = np.log(p)
    ret = log_p.diff()

    out["log_price"] = log_p
    out["ret_1d"] = ret

    # Лаги доходностей
    for k in LAGS_RET:
        out[f"ret_lag_{k}"] = ret.shift(k)

    # Лаги уровня цены (в логах)
    for k in LAGS_PRICE:
        out[f"log_price_lag_{k}"] = log_p.shift(k)

    # Скользящие средние и их соотношения
    for w in SMA_WINDOWS:
        sma = p.rolling(w).mean()
        out[f"sma_{w}"] = sma
        out[f"price_to_sma_{w}"] = p / sma - 1
    out["sma_5_20"] = out["sma_5"] / out["sma_20"] - 1
    out["sma_20_60"] = out["sma_20"] / out["sma_60"] - 1

    # Скользящая волатильность (стд логдоходностей)
    for w in VOL_WINDOWS:
        out[f"vol_{w}"] = ret.rolling(w).std() * np.sqrt(252)

    # Моментум (накопленная доходность за N дней)
    for w in [5, 10, 20, 60]:
        out[f"mom_{w}"] = log_p - log_p.shift(w)

    # Технические
    out["rsi_14"] = _rsi(p, 14)
    macd_line, signal_line, hist = _macd(p)
    out["macd"] = macd_line
    out["macd_signal"] = signal_line
    out["macd_hist"] = hist
    out["bbpctb_20"] = _bollinger_pctb(p, 20, 2.0)

    if "copper_high" in df.columns and "copper_low" in df.columns:
        out["atr_14"] = _atr(df["copper_high"], df["copper_low"], p, 14)
        out["atr_rel"] = out["atr_14"] / p  # нормированный ATR

    # Кросс-активные признаки
    for col in CROSS_ASSETS:
        if col not in df.columns:
            continue
        a = df[col]
        ar = np.log(a / a.shift(1))
        out[f"{col}_ret_1d"] = ar
        out[f"{col}_ret_5d"] = np.log(a / a.shift(5))
        out[f"{col}_ret_20d"] = np.log(a / a.shift(20))
        out[f"{col}_vol_20"] = ar.rolling(20).std() * np.sqrt(252)
        # Скользящая корреляция меди с активом
        out[f"corr_cu_{col}_60"] = ret.rolling(60).corr(ar)

    # Календарные
    out["dow"] = out.index.dayofweek
    out["dom"] = out.index.day
    out["month"] = out.index.month

    # ---- Доп. фичи: CFTC COT ----
    if "mm_net_long" in df.columns:
        mm = df["mm_net_long"]
        out["cot_mm_net_long"] = mm
        out["cot_mm_net_long_z"] = (mm - mm.rolling(52 * 5).mean()) / mm.rolling(52 * 5).std()
        out["cot_mm_net_long_chg_4w"] = mm - mm.shift(20)  # ~4 weekly reports
        out["cot_mm_net_long_chg_12w"] = mm - mm.shift(60)
    if "mm_net_long_pct" in df.columns:
        out["cot_mm_net_long_pct"] = df["mm_net_long_pct"]
    if "open_interest" in df.columns:
        oi = df["open_interest"]
        out["cot_open_interest"] = oi
        out["cot_oi_chg_4w"] = oi.pct_change(20) * 100
    if "pm_net_long" in df.columns:
        out["cot_pm_net_long"] = df["pm_net_long"]

    # ---- Доп. фичи: LME stocks ----
    if "lme_stock_total" in df.columns:
        s = df["lme_stock_total"]
        out["lme_stock_total"] = s
        out["lme_stock_log"] = np.log(s.replace(0, np.nan))
        out["lme_stock_chg_5d"] = s.pct_change(5) * 100
        out["lme_stock_chg_20d"] = s.pct_change(20) * 100
    if "lme_stock_pct_change" in df.columns:
        out["lme_stock_pct_change"] = df["lme_stock_pct_change"]

    # ---- Доп. фичи: LME (cash, 3M, премия COMEX/LME) ----
    if "lme_3m" in df.columns:
        out["lme_3m"] = df["lme_3m"]
        out["lme_3m_log"] = np.log(df["lme_3m"].replace(0, np.nan))
        # Скорость изменения LME 3M
        out["lme_3m_ret_1d"] = np.log(df["lme_3m"] / df["lme_3m"].shift(1))
        out["lme_3m_ret_5d"] = np.log(df["lme_3m"] / df["lme_3m"].shift(5))
        out["lme_3m_ret_20d"] = np.log(df["lme_3m"] / df["lme_3m"].shift(20))
    if "lme_cash" in df.columns and "lme_3m" in df.columns:
        # Спред между cash и 3M (contango/backwardation)
        out["lme_cash_3m_spread"] = (df["lme_cash"] - df["lme_3m"]) / df["lme_3m"] * 100
    if "comex_lme_premium_pct" in df.columns:
        # Главная новая фича — премия COMEX над LME
        out["comex_lme_premium_pct"] = df["comex_lme_premium_pct"]
        out["comex_lme_premium_chg_5d"] = df["comex_lme_premium_pct"].diff(5)
        out["comex_lme_premium_chg_20d"] = df["comex_lme_premium_pct"].diff(20)

    # ---- Доп. фичи: FRED ----
    for col in ["fred_dxy_broad", "fred_dgs10", "fred_fedfunds",
                "fred_cpi", "fred_indpro"]:
        if col in df.columns:
            v = df[col]
            out[col] = v
            if "cpi" in col or "indpro" in col:
                out[f"{col}_yoy"] = v.pct_change(252) * 100
            else:
                out[f"{col}_chg_20d"] = v.diff(20)

    return out


def make_target(df: pd.DataFrame, horizon_days: int) -> pd.Series:
    """Целевая переменная: лог-доходность через horizon_days дней.
       y_t = log(P_{t+h}) - log(P_t)
    Используется в обучении как многоступенчатый прогноз direct-стратегии.
    """
    log_p = np.log(df["copper"])
    return (log_p.shift(-horizon_days) - log_p).rename(f"y_h{horizon_days}")


def prepare_xy(df_raw: pd.DataFrame, horizon_days: int,
               min_coverage: float = 0.5):
    """Готовит (X, y) для обучения модели на конкретный горизонт.
    X — все фичи на момент t, y — лог-доходность за следующие horizon_days дней.
    Колонки с долей не-NaN < min_coverage отбрасываются (например, LME stocks,
    которые накапливаются с нуля и поначалу содержат только одну точку).
    Строки с любым NaN дропаются.
    """
    X = build_features(df_raw)
    y = make_target(df_raw, horizon_days)
    drop_cols = ["log_price"]
    X = X.drop(columns=[c for c in drop_cols if c in X.columns])

    # 1) Отбрасываем колонки с низким покрытием
    coverage = X.notna().mean()
    sparse = coverage[coverage < min_coverage].index.tolist()
    if sparse:
        X = X.drop(columns=sparse)

    data = X.join(y, how="inner").dropna()
    return data.drop(columns=[y.name]), data[y.name]


def select_now_features(df_raw: pd.DataFrame, train_columns: list) -> pd.DataFrame:
    """Возвращает последнюю строку фич, выровненную по train_columns.
    Используется для прогноза «сейчас».
    """
    feats = build_features(df_raw).drop(
        columns=[c for c in ["log_price"] if c in build_features(df_raw).columns],
        errors="ignore",
    )
    return feats.iloc[[-1]].reindex(columns=train_columns)


if __name__ == "__main__":
    from data_loader import load_all
    import datetime as dt
    start = (dt.date.today() - dt.timedelta(days=5 * 365 + 30)).strftime("%Y-%m-%d")
    raw = load_all(start=start)
    X, y = prepare_xy(raw, horizon_days=10)
    print(f"Фичей: {X.shape[1]}, наблюдений: {len(X)}")
    print(X.tail(3).T)
    print(f"\nТаргет y_h10 head/tail:")
    print(y.describe())
