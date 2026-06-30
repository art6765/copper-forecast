"""
data_loader.py — загрузка ежедневных рыночных данных для прогноза цены меди.

Источники (только бесплатные, без ключей):
- HG=F   — COMEX Copper Front-month, USD/lb (Yahoo Finance via yfinance)
- DX-Y.NYB — US Dollar Index (Yahoo Finance)
- CL=F   — WTI Crude, USD/barrel
- GC=F   — Gold, USD/oz
- SI=F   — Silver, USD/oz (как дополнительный proxy промышленного спроса)
- ^GSPC  — S&P 500 (риск-аппетит)
- ^TNX   — US 10Y yield x10

Все ряды приводятся к единому дневному календарю (бизнес-дни).
Кэш сохраняется в data/cache_*.csv, чтобы не дёргать сеть каждый запуск.
"""
from __future__ import annotations

import datetime as dt
import logging
import os
from pathlib import Path
from typing import Dict, Optional

import pandas as pd
import yfinance as yf

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)

TICKERS: Dict[str, str] = {
    # --- Основа ---
    "HG=F":    "copper",      # COMEX Copper, USD/lb  (целевой ряд)
    "DX-Y.NYB": "dxy",        # US Dollar Index
    "CL=F":    "wti",         # WTI Crude
    "BZ=F":    "brent",       # Brent Crude — главный драйвер рубля
    "GC=F":    "gold",        # Gold
    "SI=F":    "silver",      # Silver
    "^GSPC":   "sp500",       # S&P 500
    "^TNX":    "us10y",       # 10Y yield × 10

    # --- Расширение: валюты горнодобывающих стран ---
    "AUDUSD=X": "audusd",     # AUD/USD — Австралия (BHP, Rio Tinto)
    "USDCLP=X": "usdclp",     # USD/CLP — Чили (главный производитель меди)
    "CNY=X":    "usdcny",     # USD/CNY — Китай (главный потребитель)

    # --- Mining ETFs (опережающий индикатор) ---
    "COPX":     "copx",       # Global X Copper Miners
    "PICK":     "pick",       # iShares Metals & Mining
    "SLX":      "slx",        # VanEck Steel — proxy на индустриальный спрос

    # --- Риск-аппетит и логистика ---
    "^VIX":     "vix",        # CBOE Volatility Index — индекс страха
    "BDRY":     "bdry",       # Breakwave Dry Bulk — Baltic Dry proxy
}

LB_PER_TON = 2204.62262  # перевод USD/lb -> USD/t


def _cache_path(ticker: str) -> Path:
    safe = ticker.replace("=", "_").replace("^", "").replace(".", "_")
    return DATA_DIR / f"cache_{safe}.csv"


def _download_one(ticker: str, start: str, period: Optional[str] = None) -> pd.DataFrame:
    """Скачать один тикер с Yahoo через Ticker.history() — устойчивее, чем yf.download.
    Если period не задан, считаем число лет от start до сегодня и берём ближайший
    поддерживаемый период ('1y','2y','5y','10y','max').
    """
    if period is None:
        years = max(1, (dt.date.today() - dt.datetime.strptime(start, "%Y-%m-%d").date()).days // 365 + 1)
        if years <= 1:
            period = "1y"
        elif years <= 2:
            period = "2y"
        elif years <= 5:
            period = "5y"
        elif years <= 10:
            period = "10y"
        else:
            period = "max"

    logger.info("Загружаю %s period=%s", ticker, period)
    df = yf.Ticker(ticker).history(period=period, auto_adjust=False)
    if df is None or df.empty:
        raise RuntimeError(f"yfinance вернул пустой DataFrame для {ticker}")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] for c in df.columns]
    df.index = pd.to_datetime(df.index).tz_localize(None)
    # Обрежем по start
    df = df[df.index >= pd.Timestamp(start)]
    return df


def fetch_ticker(ticker: str, start: str, use_cache: bool = True,
                 refresh: bool = False) -> pd.DataFrame:
    """Загрузка одного тикера с дисковым кэшем.
    При flaky yfinance — fallback на старый кэш, чтобы не падать целиком.
    """
    path = _cache_path(ticker)
    cached = None
    if path.exists():
        try:
            cached = pd.read_csv(path, parse_dates=["Date"]).set_index("Date")
        except Exception:
            cached = None

    if use_cache and cached is not None and not refresh:
        last = cached.index.max()
        if last >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=3):
            return cached
        try:
            tail_start = (last + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
            tail = _download_one(ticker, tail_start)
            df = pd.concat([cached, tail])
            df = df[~df.index.duplicated(keep="last")].sort_index()
        except Exception as exc:
            logger.warning("Не удалось обновить кэш %s: %s — использую старый", ticker, exc)
            df = cached
    else:
        try:
            df = _download_one(ticker, start)
        except Exception as exc:
            if cached is not None:
                logger.warning("yfinance %s: %s — fallback на старый кэш", ticker, exc)
                return cached
            raise

    df.to_csv(path, index_label="Date")
    return df


def load_all(start: str = "2020-01-01", refresh: bool = False,
             include_cot: bool = True, include_lme_stocks: bool = True,
             include_lme_price: bool = True,
             include_fred: bool = True,
             include_cbr: bool = True) -> pd.DataFrame:
    """
    Возвращает единый DataFrame с дневной частотой и колонками:
      copper, copper_high, copper_low, copper_volume,
      dxy, wti, gold, silver, sp500, us10y,
      + (опционально) mm_net_long, mm_net_long_pct, open_interest, pm_net_long,
      + (опционально) lme_stock_total, lme_stock_change, lme_stock_pct_change,
      + (опционально) fred_dxy_broad, fred_dgs10, fred_fedfunds, fred_cpi, fred_indpro

    Индекс — деловые дни США (Mon-Fri, без выходных).
    Пропуски прокидываются forward-fill, но не более 5 подряд.
    """
    closes = {}
    extra = {}

    for ticker, name in TICKERS.items():
        try:
            df = fetch_ticker(ticker, start=start, refresh=refresh)
        except Exception as exc:
            logger.warning("Пропускаю %s: %s", ticker, exc)
            continue

        # Колонка Close может называться по-разному
        close_col = "Close" if "Close" in df.columns else "Adj Close"
        closes[name] = df[close_col]
        if name == "copper":
            # Сохраняем H/L/V для волатильности и фичей
            if "High" in df.columns:
                extra["copper_high"] = df["High"]
            if "Low" in df.columns:
                extra["copper_low"] = df["Low"]
            if "Volume" in df.columns:
                extra["copper_volume"] = df["Volume"]

    if "copper" not in closes:
        raise RuntimeError("Не удалось получить данные по меди — основной ряд отсутствует.")

    out = pd.concat(closes, axis=1)
    for k, v in extra.items():
        out[k] = v

    # Приводим к бизнес-дням и заполняем небольшие пропуски
    bdays = pd.bdate_range(out.index.min(), out.index.max())
    out = out.reindex(bdays)
    out = out.ffill(limit=5).dropna(subset=["copper"])

    # --- Дополнительные источники (CFTC COT, LME stocks, LME price, FRED, ЦБ РФ) ---
    if include_cot or include_lme_stocks or include_lme_price or include_fred or include_cbr:
        try:
            from extra_sources import (fetch_cftc_cot, cot_to_daily,
                                        fetch_lme_stocks_westmetall,
                                        fetch_lme_copper_price,
                                        fetch_fred_bundle,
                                        fetch_cbr_usdrub,
                                        fetch_cbr_key_rate)
        except ImportError as exc:
            logger.warning("extra_sources недоступен: %s", exc)
            fetch_cftc_cot = fetch_lme_stocks_westmetall = None
            fetch_lme_copper_price = fetch_fred_bundle = None
            fetch_cbr_usdrub = fetch_cbr_key_rate = None

        if include_cot and fetch_cftc_cot is not None:
            try:
                years = max(1, (out.index.max() - out.index.min()).days // 365 + 1)
                cot = fetch_cftc_cot(years=years, refresh=refresh)
                cot_d = cot.reindex(out.index, method="ffill")
                for col in ["open_interest", "mm_net_long", "mm_net_long_pct",
                            "pm_net_long", "other_net_long"]:
                    if col in cot_d.columns:
                        out[col] = cot_d[col]
                logger.info("CFTC COT добавлен (последний MM net long = %.0f)",
                            cot["mm_net_long"].iloc[-1] if not cot.empty else 0)
            except Exception as exc:
                logger.warning("CFTC COT не загружен: %s", exc)

        if include_lme_stocks and fetch_lme_stocks_westmetall is not None:
            try:
                stk = fetch_lme_stocks_westmetall(refresh=refresh)
                if not stk.empty:
                    stk_d = stk.reindex(out.index, method="ffill")
                    for col in ["lme_stock_total", "lme_stock_change",
                                "lme_stock_pct_change"]:
                        if col in stk_d.columns:
                            out[col] = stk_d[col]
                    logger.info("LME stocks (Westmetall): последний total = %.0f т",
                                stk["lme_stock_total"].iloc[-1])
            except Exception as exc:
                logger.warning("LME stocks не загружены: %s", exc)

        # ---------- LME цена (cash + 3M) — гибрид с COMEX ----------
        if include_lme_price and fetch_lme_copper_price is not None:
            try:
                lme = fetch_lme_copper_price(refresh=refresh)
                if not lme.empty:
                    lme_d = lme.reindex(out.index, method="ffill")
                    for col in ["lme_cash", "lme_3m"]:
                        if col in lme_d.columns:
                            out[col] = lme_d[col]
                    # Если ещё нет полной истории LME stocks — дополним из этого источника
                    if "lme_stock_total" not in out.columns and "lme_stock" in lme_d.columns:
                        out["lme_stock_total"] = lme_d["lme_stock"]
                    # Премия COMEX над LME 3M (в %).
                    # COMEX HG=F в USD/lb, LME в USD/t — приводим через LB_PER_TON.
                    if "lme_3m" in out.columns:
                        out["comex_lme_premium_pct"] = (
                            (out["copper"] * LB_PER_TON) / out["lme_3m"] - 1
                        ) * 100
                    logger.info("LME prices: %d строк истории, последний 3M = %.0f USD/т",
                                len(lme), lme["lme_3m"].iloc[-1])
            except Exception as exc:
                logger.warning("LME цена не загружена: %s", exc)

        if include_fred and fetch_fred_bundle is not None:
            try:
                fred = fetch_fred_bundle(start, refresh=refresh)
                if not fred.empty:
                    fred_d = fred.reindex(out.index, method="ffill")
                    for col in fred_d.columns:
                        out[col] = fred_d[col]
                    logger.info("FRED добавлен: %d рядов", fred.shape[1])
            except Exception as exc:
                logger.warning("FRED не загружен: %s", exc)

        # ---------- Курс доллара ЦБ РФ (USD/RUB) — для рублёвых цен и прогноза ----------
        if include_cbr and fetch_cbr_usdrub is not None:
            try:
                fx = fetch_cbr_usdrub(start=start, refresh=refresh)
                if not fx.empty:
                    fx_d = fx.reindex(out.index, method="ffill")
                    out["usdrub"] = fx_d["usdrub"]
                    logger.info("ЦБ РФ USD/RUB добавлен: последний %.2f ₽/$",
                                float(fx["usdrub"].iloc[-1]))
            except Exception as exc:
                logger.warning("ЦБ РФ USD/RUB не загружен: %s", exc)

        # ---------- Ключевая ставка ЦБ РФ — драйвер рубля (carry) ----------
        if include_cbr and fetch_cbr_key_rate is not None:
            try:
                kr = fetch_cbr_key_rate(start=start, refresh=refresh)
                if not kr.empty:
                    kr_d = kr.reindex(out.index, method="ffill")
                    out["cbr_key_rate"] = kr_d["cbr_key_rate"]
                    logger.info("ЦБ РФ ключевая ставка добавлена: последняя %.2f%%",
                                float(kr["cbr_key_rate"].iloc[-1]))
            except Exception as exc:
                logger.warning("ЦБ РФ ключевая ставка не загружена: %s", exc)

    return out


def copper_usd_per_ton(series: pd.Series) -> pd.Series:
    """Перевод USD/lb (HG=F) → USD/t."""
    return series * LB_PER_TON


def fetch_copper_spot_now():
    """Свежая внутридневная котировка меди COMEX (HG=F, задержка ~15 мин).

    Прогноз строится на дневном закрытии; эта функция даёт самую свежую цену
    «сейчас» — чтобы показать текущую цену в течение дня. None при сбое.
    Возвращает {price_lb, price_usd_t, time}.
    """
    try:
        h = yf.Ticker("HG=F").history(period="1d", interval="5m", auto_adjust=False)
        if h is None or h.empty:
            return None
        lb = float(h["Close"].dropna().iloc[-1])
        return {"price_lb": lb, "price_usd_t": lb * LB_PER_TON, "time": h.index[-1]}
    except Exception:
        return None


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    five_years_ago = (dt.date.today() - dt.timedelta(days=5 * 365 + 30)).strftime("%Y-%m-%d")
    df = load_all(start=five_years_ago, refresh=True)
    print(df.tail())
    print(f"\nДиапазон: {df.index.min().date()} → {df.index.max().date()}, {len(df)} строк")
    print(f"Последняя цена меди: {df['copper'].iloc[-1]:.4f} USD/lb "
          f"= {copper_usd_per_ton(df['copper']).iloc[-1]:.2f} USD/t")
