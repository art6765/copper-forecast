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
# Версия набора фич. Подмешивается в сигнатуры диск-кэша прогнозов (app.py,
# forecast.py): при изменении состава признаков — БУМП этой строки, иначе кэш
# вернёт устаревший прогноз, построенный на старом наборе фич.
FEATURE_VERSION = "f2"   # f2: + Brent, ключевая ставка ЦБ, carry

LAGS_PRICE = [1, 5, 20]
SMA_WINDOWS = [5, 10, 20, 60]
VOL_WINDOWS = [10, 20, 60]
CROSS_ASSETS = [
    "dxy", "wti", "brent", "gold", "silver", "sp500", "us10y",
    "audusd", "usdclp", "usdcny",      # валюты горнодобыч. стран
    "copx", "pick", "slx",              # mining ETFs
    "vix", "bdry",                      # риск + логистика
]


# ====================================================================
#  Человекочитаемые названия активов (для расшифровки признаков)
# ====================================================================
ASSET_LABELS = {
    "dxy":    "доллар (DXY)",
    "wti":    "нефть WTI",
    "brent":  "нефть Brent",
    "gold":   "золото",
    "silver": "серебро",
    "sp500":  "S&P 500",
    "us10y":  "доходность US 10Y",
    "audusd": "австралийский доллар (AUD/USD)",
    "usdclp": "чилийский песо (USD/CLP)",
    "usdcny": "китайский юань (USD/CNY)",
    "copx":   "ETF медных майнеров (COPX)",
    "pick":   "ETF металлов и добычи (PICK)",
    "slx":    "ETF сталелитейщиков (SLX)",
    "vix":    "индекс страха (VIX)",
    "bdry":   "ставки фрахта (Baltic Dry)",
}


def describe_feature(name: str) -> str:
    """Человекочитаемое описание признака по его имени.
    Покрывает все паттерны из build_features(). Возвращает строку на русском.
    """
    import re

    # Точные совпадения
    exact = {
        "log_price": "Логарифм цены меди",
        "ret_1d": "Дневная доходность меди (лог)",
        "rsi_14": "RSI(14) — индекс силы тренда (0-100): >70 перекуплен, <30 перепродан",
        "macd": "MACD — разница быстрой и медленной скользящих средних",
        "macd_signal": "Сигнальная линия MACD (EMA-9 от MACD)",
        "macd_hist": "MACD-гистограмма (MACD − сигнал); пересечение нуля = разворот",
        "bbpctb_20": "Bollinger %B(20): где цена внутри полос ±2σ (0=низ, 1=верх)",
        "atr_14": "ATR(14) — средний истинный диапазон, абсолютная волатильность",
        "atr_rel": "ATR(14), нормированный на цену (волатильность в %)",
        "sma_5_20": "Соотношение SMA-5 / SMA-20: >0 краткосрочный тренд вверх",
        "sma_20_60": "Соотношение SMA-20 / SMA-60: >0 среднесрочный тренд вверх",
        "dow": "День недели (0=Пн … 4=Пт) — сезонность внутри недели",
        "dom": "День месяца (1-31)",
        "month": "Месяц (1-12) — годовая сезонность",
        "lme_3m": "Цена LME 3-month, USD/т (глобальный baseline)",
        "lme_3m_log": "Логарифм цены LME 3M",
        "lme_cash_3m_spread": "Спред LME cash − 3M, %: >0 бэквардация, <0 контанго",
        "comex_lme_premium_pct": "Премия COMEX над LME 3M, % — индикатор тарифного режима США",
        "cot_mm_net_long": "CFTC: чистая длинная позиция хедж-фондов, контрактов",
        "cot_mm_net_long_z": "COT net long как z-score за 5 лет: >2 экстремальный перегрев",
        "cot_mm_net_long_pct": "COT net long как % от открытого интереса",
        "cot_open_interest": "Открытый интерес COMEX — общее число контрактов",
        "cot_pm_net_long": "CFTC: чистая позиция производителей/торговцев (хеджеры)",
        "lme_stock_total": "Складские запасы меди на LME, тонн",
        "lme_stock_log": "Логарифм складских запасов LME",
        "lme_stock_pct_change": "Дневное изменение запасов LME, %",
        "cbr_key_rate": "Ключевая ставка ЦБ РФ, % годовых — драйвер рубля",
        "cbr_key_rate_chg_60d": "Изменение ключевой ставки ЦБ за 60 дней, п.п.",
        "cbr_key_rate_chg_120d": "Изменение ключевой ставки ЦБ за 120 дней, п.п.",
        "carry_rub_usd": "Carry: дифференциал ставок ЦБ РФ − ФРС, п.п. (главный фундаментал FX)",
        "carry_rub_usd_chg_60d": "Изменение carry (ставка ЦБ − ФРС) за 60 дней, п.п.",
    }
    if name in exact:
        return exact[name]

    # Паттерны
    m = re.match(r"ret_lag_(\d+)$", name)
    if m:
        return f"Доходность меди {m.group(1)} дн. назад"

    m = re.match(r"log_price_lag_(\d+)$", name)
    if m:
        return f"Логарифм цены меди {m.group(1)} дн. назад"

    m = re.match(r"sma_(\d+)$", name)
    if m:
        w = m.group(1)
        return f"Скользящее среднее цены за {w} дней = (P_t + P_t-1 + … + P_t-{int(w)-1}) / {w}"

    m = re.match(r"price_to_sma_(\d+)$", name)
    if m:
        return f"Отклонение цены от SMA-{m.group(1)}: P / SMA − 1 (насколько выше/ниже среднего)"

    m = re.match(r"vol_(\d+)$", name)
    if m:
        return f"Годовая волатильность за {m.group(1)} дней (стд доходностей × √252)"

    m = re.match(r"mom_(\d+)$", name)
    if m:
        return f"Моментум за {m.group(1)} дней: накопленная доходность ln(P_t / P_t-{m.group(1)})"

    # Кросс-активные
    m = re.match(r"(\w+?)_ret_(\d+)d$", name)
    if m and m.group(1) in ASSET_LABELS:
        return f"Изменение {ASSET_LABELS[m.group(1)]} за {m.group(2)} дн. (лог)"

    m = re.match(r"(\w+?)_vol_20$", name)
    if m and m.group(1) in ASSET_LABELS:
        return f"Волатильность {ASSET_LABELS[m.group(1)]} за 20 дней"

    m = re.match(r"corr_cu_(\w+?)_60$", name)
    if m and m.group(1) in ASSET_LABELS:
        return f"Скользящая 60-дн. корреляция меди с {ASSET_LABELS[m.group(1)]}"

    # COT-изменения
    m = re.match(r"cot_mm_net_long_chg_(\d+)w$", name)
    if m:
        return f"Изменение COT net long за {m.group(1)} недель"
    if name == "cot_oi_chg_4w":
        return "Изменение открытого интереса за 4 недели, %"

    # LME stocks изменения
    m = re.match(r"lme_stock_chg_(\d+)d$", name)
    if m:
        return f"Изменение запасов LME за {m.group(1)} дней, %"

    # LME 3M доходности
    m = re.match(r"lme_3m_ret_(\d+)d$", name)
    if m:
        return f"Изменение цены LME 3M за {m.group(1)} дн. (лог)"

    # Премия изменения
    m = re.match(r"comex_lme_premium_chg_(\d+)d$", name)
    if m:
        return f"Изменение премии COMEX/LME за {m.group(1)} дней"

    # FRED
    fred = {
        "fred_dxy_broad": "FRED: широкий индекс доллара (DTWEXBGS)",
        "fred_dgs10": "FRED: доходность US 10Y Treasury",
        "fred_fedfunds": "FRED: эффективная ставка ФРС",
        "fred_cpi": "FRED: индекс потребительских цен США (CPI)",
        "fred_indpro": "FRED: индекс промышленного производства США",
    }
    if name in fred:
        return fred[name]
    m = re.match(r"(fred_\w+)_chg_20d$", name)
    if m and m.group(1) in fred:
        return f"{fred[m.group(1)]} — изменение за 20 дней"
    m = re.match(r"(fred_\w+)_yoy$", name)
    if m and m.group(1) in fred:
        return f"{fred[m.group(1)]} — изменение год к году, %"

    # Сезонные (если добавятся)
    m = re.match(r"seasonal_h(\d+)$", name)
    if m:
        return f"Сезонный сигнал: средняя историческая доходность на {m.group(1)} дн. вперёд"

    return name  # fallback — само имя


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

    # ---- Доп. фичи: ключевая ставка ЦБ РФ + carry (драйверы рубля) ----
    # Ставка — это уровень в % годовых, поэтому НЕ обрабатываем её как ценовой
    # ряд (лог-доходность ставки бессмысленна): берём уровень и его изменение.
    # carry = дифференциал ставок (ЦБ РФ − ФРС) — главный фундаментал для FX.
    if "cbr_key_rate" in df.columns:
        kr = df["cbr_key_rate"]
        out["cbr_key_rate"] = kr
        out["cbr_key_rate_chg_60d"] = kr.diff(60)
        out["cbr_key_rate_chg_120d"] = kr.diff(120)
        if "fred_fedfunds" in df.columns:
            carry = kr - df["fred_fedfunds"]
            out["carry_rub_usd"] = carry
            out["carry_rub_usd_chg_60d"] = carry.diff(60)

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
