"""
extra_sources.py — дополнительные бесплатные источники сверх yfinance:

1. CFTC COT (CMX copper 085692, Disaggregated Futures Only).
2. LME copper stocks через Westmetall (зеркало LME, daily HTML-таблица).
3. FRED API (опционально, если задан FRED_API_KEY): DXY, ставки, PMI, CPI.

Все источники бесплатные. Без API-ключей, кроме FRED (бесплатная регистрация).

ВАЖНО: на части macOS-сборок Anaconda есть проблема с SSL EOF при подключении к
ряду сайтов (CFTC, FRED). Поэтому используется urllib с принудительным
TLSv1.2-минимумом и кастомным User-Agent — это обходит баг.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
import subprocess
import time
import datetime as dt
import io
from pathlib import Path
from typing import Optional, Dict, List
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import pandas as pd

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# ============================================================
#  Универсальный HTTP-helper с обходом SSL-багов Anaconda macOS
# ============================================================

def _get(url: str, params: Optional[Dict[str, str]] = None,
         timeout: int = 25, user_agent: str = "Mozilla/5.0",
         retries: int = 3) -> bytes:
    """HTTP GET с urllib + TLSv1.2 minimum и retry с экспоненциальной задержкой.
    Если urllib падает с SSLEOFError — fallback на subprocess curl.
    """
    if params:
        url = url + ("&" if "?" in url else "?") + urlencode(params)
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2

    last_exc = None
    for attempt in range(retries):
        try:
            req = Request(url, headers={"User-Agent": user_agent})
            with urlopen(req, context=ctx, timeout=timeout) as r:
                return r.read()
        except Exception as exc:
            last_exc = exc
            logger.debug("HTTP attempt %d/%d failed: %s", attempt + 1, retries, exc)
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))

    # Fallback: curl, если установлен
    try:
        logger.warning("urllib не справился (%s) — пробую curl", last_exc)
        result = subprocess.run(
            ["curl", "-sSL", "--max-time", str(timeout),
             "-A", user_agent, url],
            capture_output=True, check=True, timeout=timeout + 5,
        )
        return result.stdout
    except Exception as exc:
        logger.error("curl fallback тоже не сработал: %s", exc)
        raise last_exc if last_exc else exc


def _get_json(url: str, params: Optional[Dict[str, str]] = None,
              timeout: int = 25) -> List[dict]:
    return json.loads(_get(url, params, timeout))


# ============================================================
#  CFTC Commitments of Traders — медь COMEX (085692)
# ============================================================

CFTC_DISAGG_URL = "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
COPPER_CONTRACT = "085692"  # CFTC contract code for COMEX copper


def fetch_cftc_cot(years: int = 5, refresh: bool = False) -> pd.DataFrame:
    """
    Загрузка CFTC Disaggregated COT для меди (COMEX 085692).
    Частота — недельная (Tuesday data, publishe Friday).

    Возвращает DataFrame с колонками:
      open_interest_all
      m_money_net_long      (Money Manager net long, контрактов)
      m_money_net_long_pct  (доля от OI)
      prod_merc_net_long
      other_rept_net_long
      nonrept_net_long
      mm_long_share, mm_short_share

    Все в integer-контрактах, кроме *_pct и *_share (доля).
    """
    cache_path = DATA_DIR / "cache_cftc_cot.csv"
    if cache_path.exists() and not refresh:
        df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
        # Если кэш свежий (новее 7 дней) — используем
        if df.index.max() >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=7):
            return df

    # Грузим из Socrata с пагинацией (chunk небольшой — устойчивее по SSL)
    rows: List[dict] = []
    limit = 500
    offset = 0
    while True:
        chunk = _get_json(CFTC_DISAGG_URL, {
            "cftc_contract_market_code": COPPER_CONTRACT,
            "$limit": str(limit),
            "$offset": str(offset),
            "$order": "report_date_as_yyyy_mm_dd DESC",
        })
        if not chunk:
            break
        rows.extend(chunk)
        if len(chunk) < limit:
            break
        offset += limit
        if offset > 5000:
            break

    if not rows:
        raise RuntimeError("CFTC: пустой ответ")

    df = pd.DataFrame(rows)
    df["date"] = pd.to_datetime(df["report_date_as_yyyy_mm_dd"])
    df = df.set_index("date").sort_index()

    # Конвертим в int
    numeric_cols = [
        "open_interest_all",
        "m_money_positions_long_all", "m_money_positions_short_all",
        "prod_merc_positions_long", "prod_merc_positions_short",
        "other_rept_positions_long", "other_rept_positions_short",
        "nonrept_positions_long_all", "nonrept_positions_short_all",
    ]
    for c in numeric_cols:
        df[c] = pd.to_numeric(df[c], errors="coerce")

    out = pd.DataFrame(index=df.index)
    out["open_interest"] = df["open_interest_all"]
    out["mm_long"] = df["m_money_positions_long_all"]
    out["mm_short"] = df["m_money_positions_short_all"]
    out["mm_net_long"] = out["mm_long"] - out["mm_short"]
    out["mm_net_long_pct"] = out["mm_net_long"] / out["open_interest"] * 100
    out["mm_long_share"] = out["mm_long"] / out["open_interest"] * 100
    out["mm_short_share"] = out["mm_short"] / out["open_interest"] * 100

    out["pm_net_long"] = (df["prod_merc_positions_long"] -
                          df["prod_merc_positions_short"])
    out["other_net_long"] = (df["other_rept_positions_long"] -
                              df["other_rept_positions_short"])
    out["nonrept_net_long"] = (df["nonrept_positions_long_all"] -
                                df["nonrept_positions_short_all"])

    cutoff = pd.Timestamp(dt.date.today()) - pd.Timedelta(days=years * 365 + 30)
    out = out[out.index >= cutoff]

    out.to_csv(cache_path, index_label="date")
    logger.info("CFTC COT: %d недельных строк, %s → %s",
                len(out), out.index.min().date(), out.index.max().date())
    return out


def cot_to_daily(cot: pd.DataFrame, index: pd.DatetimeIndex) -> pd.DataFrame:
    """Forward-fill COT на дневную сетку (отчёт публикуется в пятницу за вторник)."""
    return cot.reindex(index, method="ffill")


# ============================================================
#  LME copper stocks через Westmetall
# ============================================================

WESTMETALL_OVERVIEW_URL = "https://www.westmetall.com/en/markdaten.php"
WESTMETALL_LME_CASH_URL = "https://www.westmetall.com/en/markdaten.php?action=table&field=LME_Cu_cash"


def fetch_lme_copper_price(refresh: bool = False) -> pd.DataFrame:
    """
    Парсинг таблицы LME_Cu_cash с Westmetall.
    Бесплатно. Отдаёт около 100 дней истории за один запрос.
    Кэш — data/cache_lme_price.csv — накапливается при каждом запуске.

    Колонки:
      lme_cash      — LME Copper Cash-Settlement, USD/т (spot)
      lme_3m        — LME Copper 3-month, USD/т (главный baseline в аналитике)
      lme_stock     — LME copper warehouse stocks, тонн
    """
    cache_path = DATA_DIR / "cache_lme_price.csv"
    cached = None
    if cache_path.exists():
        try:
            cached = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
            if not refresh and cached.index.max() >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=2):
                return cached
        except Exception:
            cached = None

    try:
        html = _get(WESTMETALL_LME_CASH_URL, timeout=20).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Westmetall LME_Cu_cash fetch failed: %s", exc)
        if cached is not None:
            return cached
        return pd.DataFrame(columns=["lme_cash", "lme_3m", "lme_stock"])

    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception as exc:
        logger.warning("read_html LME_Cu_cash failed: %s", exc)
        if cached is not None:
            return cached
        return pd.DataFrame(columns=["lme_cash", "lme_3m", "lme_stock"])

    if not tables:
        if cached is not None:
            return cached
        return pd.DataFrame(columns=["lme_cash", "lme_3m", "lme_stock"])

    df = tables[0].copy()
    # Стандартные колонки Westmetall:
    # ['date', 'LME Copper Cash-Settlement', 'LME Copper 3-month', 'LME Copper stock']
    rename = {
        "date": "date",
        "LME Copper Cash-Settlement": "lme_cash",
        "LME Copper 3-month": "lme_3m",
        "LME Copper stock": "lme_stock",
    }
    df = df.rename(columns=rename)
    keep = [c for c in ["date", "lme_cash", "lme_3m", "lme_stock"] if c in df.columns]
    df = df[keep]

    # Парсим дату
    for fmt in ("%d. %B %Y", "%d. %b %Y"):
        try:
            df["date"] = pd.to_datetime(df["date"], format=fmt)
            break
        except Exception:
            continue
    else:
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
    df = df.dropna(subset=["date"]).set_index("date").sort_index()

    # Числа: убираем запятые, пробелы
    for c in ["lme_cash", "lme_3m", "lme_stock"]:
        if c in df.columns:
            df[c] = (df[c].astype(str)
                          .str.replace(",", "")
                          .str.replace(" ", "")
                          .replace("nan", "")
                          .pipe(pd.to_numeric, errors="coerce"))

    # Мердж с кэшем (если был)
    if cached is not None:
        merged = pd.concat([cached, df])
        merged = merged[~merged.index.duplicated(keep="last")].sort_index()
        df = merged

    df.to_csv(cache_path, index_label="date")
    logger.info("Westmetall LME prices: %d строк, %s → %s",
                len(df), df.index.min().date(), df.index.max().date())
    return df


def _parse_westmetall_snapshot(html: str) -> Optional[Dict]:
    """Извлекаем строку Copper из таблицы 'LME Stocks' на главной Westmetall.
    Колонки: 'in tons', '<date>', 'Changes'. Возвращаем dict с lme_stock_total и change.
    """
    try:
        tables = pd.read_html(io.StringIO(html))
    except Exception:
        return None

    for t in tables:
        # Ищем таблицу со столбцом 'LME Stocks' и строкой 'Copper'
        cols_str = " ".join(str(c) for c in t.columns)
        if "LME Stocks" not in cols_str and "tons" not in cols_str.lower():
            continue
        first_col = t.iloc[:, 0].astype(str)
        copper_rows = t[first_col.str.lower() == "copper"]
        if copper_rows.empty:
            continue
        row = copper_rows.iloc[0]
        try:
            stock = int(str(row.iloc[1]).replace(",", "").replace(" ", ""))
            change = int(str(row.iloc[2]).replace(",", "").replace(" ", "").replace("+", ""))
        except Exception:
            continue
        # Дата — в заголовке столбца (например, '22. May 2026')
        try:
            date_header = str(t.columns[1])
            for fmt in ("%d. %b %Y", "%d. %B %Y"):
                try:
                    d = pd.to_datetime(date_header, format=fmt)
                    break
                except Exception:
                    d = None
            if d is None:
                d = pd.to_datetime(date_header, errors="coerce")
            if pd.isna(d):
                d = pd.Timestamp(dt.date.today())
        except Exception:
            d = pd.Timestamp(dt.date.today())
        return {"date": d.normalize(), "lme_stock_total": stock,
                "lme_stock_change": change}
    return None


def fetch_lme_stocks_westmetall(refresh: bool = False) -> pd.DataFrame:
    """
    Возвращает накопленную историю LME copper stocks из Westmetall.

    Westmetall публикует только snapshot (один день) в открытом доступе, поэтому:
      1. При каждом вызове берём сегодняшнее значение из обзорной страницы.
      2. Добавляем в кэш cache_lme_stocks.csv (idempotent — не дублирует).
      3. Возвращаем накопленную историю.

    Колонки:
      lme_stock_total      — общие складские запасы LME, тонн
      lme_stock_change     — изменение к предыдущему дню (из колонки 'Changes')
      lme_stock_pct_change — относительное изменение (вычисляется)

    Если в кэше уже есть данные за сегодня — повторный запрос не делается.
    """
    cache_path = DATA_DIR / "cache_lme_stocks.csv"
    cached = None
    if cache_path.exists():
        cached = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
        if not refresh and not cached.empty and \
           cached.index.max().date() == dt.date.today():
            return cached

    try:
        html = _get(WESTMETALL_OVERVIEW_URL, timeout=15).decode("utf-8", errors="replace")
    except Exception as exc:
        logger.warning("Westmetall fetch failed: %s", exc)
        if cached is not None and not cached.empty:
            return cached
        return pd.DataFrame(columns=["lme_stock_total", "lme_stock_change",
                                      "lme_stock_pct_change"])

    snap = _parse_westmetall_snapshot(html)
    if snap is None:
        logger.warning("Westmetall: не удалось распарсить snapshot")
        if cached is not None and not cached.empty:
            return cached
        return pd.DataFrame(columns=["lme_stock_total", "lme_stock_change",
                                      "lme_stock_pct_change"])

    # Добавляем snapshot в кэш
    new_row = pd.DataFrame(
        [{"lme_stock_total": snap["lme_stock_total"],
          "lme_stock_change": snap["lme_stock_change"]}],
        index=pd.DatetimeIndex([snap["date"]], name="date"),
    )
    if cached is not None and not cached.empty:
        df = pd.concat([cached.drop(columns=["lme_stock_pct_change"], errors="ignore"),
                         new_row])
        df = df[~df.index.duplicated(keep="last")].sort_index()
    else:
        df = new_row

    df["lme_stock_pct_change"] = df["lme_stock_change"] / (df["lme_stock_total"] - df["lme_stock_change"]) * 100
    df.to_csv(cache_path, index_label="date")
    logger.info("Westmetall LME stocks snapshot: %s = %d t (Δ %+d t); накоплено %d строк",
                snap["date"].date(), snap["lme_stock_total"], snap["lme_stock_change"],
                len(df))
    return df


# ============================================================
#  FRED API (опционально, требуется ключ)
# ============================================================

FRED_BASE = "https://api.stlouisfed.org/fred/series/observations"

# Полезные ряды для меди
FRED_SERIES = {
    "fred_dxy_broad": "DTWEXBGS",   # Trade-weighted Dollar Index (Broad)
    "fred_dgs10":     "DGS10",      # 10-Year Treasury
    "fred_fedfunds":  "DFF",        # Effective Federal Funds Rate
    "fred_cpi":       "CPIAUCSL",   # CPI All Urban
    "fred_indpro":    "INDPRO",     # Industrial Production
    "fred_copper_imf": "PCOPPUSDM", # IMF Copper price ($/mt)
}


def _get_fred_key() -> Optional[str]:
    """Поиск ключа FRED: env → Streamlit secrets (для Cloud) → None."""
    key = os.environ.get("FRED_API_KEY")
    if key:
        return key
    # Опционально — st.secrets (если запущены под Streamlit)
    try:
        import streamlit as st
        return st.secrets.get("FRED_API_KEY")
    except Exception:
        return None


def fetch_fred_series(series_id: str, start: str,
                      api_key: Optional[str] = None) -> pd.Series:
    """Один ряд FRED. Требует FRED_API_KEY (env, st.secrets или аргумент)."""
    api_key = api_key or _get_fred_key()
    if not api_key:
        raise RuntimeError(
            "FRED_API_KEY не задан. Зарегистрируйтесь на "
            "https://fred.stlouisfed.org/docs/api/api_key.html "
            "и установите переменную окружения FRED_API_KEY "
            "или добавьте в Streamlit secrets."
        )
    js = _get_json(FRED_BASE, {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "observation_start": start,
    })
    obs = js.get("observations", [])
    if not obs:
        return pd.Series(dtype=float, name=series_id)
    df = pd.DataFrame(obs)
    df["date"] = pd.to_datetime(df["date"])
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return df.set_index("date")["value"].rename(series_id)


def fetch_fred_bundle(start: str, refresh: bool = False) -> pd.DataFrame:
    """
    Тянет всю стандартную FRED-корзину разом.
    Если FRED_API_KEY не задан — возвращает пустой DataFrame с предупреждением
    (без падения).
    """
    api_key = _get_fred_key()
    if not api_key:
        logger.warning("FRED_API_KEY не задан — FRED-фичи пропускаются")
        return pd.DataFrame()

    cache_path = DATA_DIR / "cache_fred.csv"
    if cache_path.exists() and not refresh:
        df = pd.read_csv(cache_path, parse_dates=["date"]).set_index("date").sort_index()
        if df.index.max() >= pd.Timestamp(dt.date.today()) - pd.Timedelta(days=7):
            return df

    out: Dict[str, pd.Series] = {}
    for col, sid in FRED_SERIES.items():
        try:
            s = fetch_fred_series(sid, start, api_key)
            out[col] = s
        except Exception as exc:
            logger.warning("FRED %s failed: %s", sid, exc)
    if not out:
        return pd.DataFrame()
    df = pd.concat(out, axis=1).sort_index()
    df.to_csv(cache_path, index_label="date")
    logger.info("FRED bundle: %d рядов, %d строк", df.shape[1], len(df))
    return df


# ============================================================
#  Main: для отладки
# ============================================================

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    print("=== CFTC COT ===")
    cot = fetch_cftc_cot(years=5, refresh=True)
    print(cot.tail(3))

    print("\n=== Westmetall LME stocks ===")
    try:
        stk = fetch_lme_stocks_westmetall(refresh=True)
        print(stk.tail(3))
    except Exception as exc:
        print(f"Westmetall fail: {exc}")

    print("\n=== FRED (если есть ключ) ===")
    fr = fetch_fred_bundle("2021-01-01")
    if not fr.empty:
        print(fr.tail(3))
    else:
        print("(пропущено — нет ключа)")
