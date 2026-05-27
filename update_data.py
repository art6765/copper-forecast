"""
update_data.py — скрипт для ежедневного обновления кэша всех источников.

Запускается из cron или вручную:
    python update_data.py            # обновить все доступные источники
    python update_data.py --quiet    # без подробного лога

Что делает:
  1. yfinance: HG=F + DXY + WTI + Gold + Silver + SP500 + US10Y.
  2. CFTC COT (если четверг/пятница — новая порция).
  3. Westmetall LME stocks (snapshot за сегодня → накопительный CSV).
  4. FRED (если задан FRED_API_KEY).

Атомарно: если какой-то источник упал — обновляет остальные, не падает целиком.
Возвращает код 0 при успехе хотя бы базового набора (медь), иначе 1.

Crontab (ежедневно в 23:30 локального времени):
    30 23 * * * /usr/bin/python3 /path/to/copper_forecast_mvp/update_data.py >> /tmp/copper_update.log 2>&1
"""
from __future__ import annotations

import argparse
import datetime as dt
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))


def main():
    parser = argparse.ArgumentParser(description="Daily refresh всех источников")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--years", type=int, default=5)
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.WARNING if args.quiet else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )
    log = logging.getLogger("update_data")

    started = dt.datetime.now()
    start_date = (dt.date.today() - dt.timedelta(days=args.years * 365 + 30)).strftime("%Y-%m-%d")
    base_ok = False

    # 1. yfinance — критично
    try:
        from data_loader import load_all
        df = load_all(start=start_date, refresh=True,
                       include_cot=True, include_lme_stocks=True,
                       include_fred=True)
        log.info("✅ yfinance + extras: %d строк, последняя дата %s",
                 len(df), df.index.max().date())
        base_ok = True
    except Exception as exc:
        log.error("❌ load_all не сработал: %s", exc)

    # 2. CFTC COT — гарантированный refresh
    try:
        from extra_sources import fetch_cftc_cot
        cot = fetch_cftc_cot(years=args.years, refresh=True)
        log.info("✅ CFTC COT: %d недель, последняя %s",
                 len(cot), cot.index.max().date())
    except Exception as exc:
        log.warning("⚠️  CFTC COT: %s", exc)

    # 3. Westmetall LME stocks — snapshot за сегодня
    try:
        from extra_sources import fetch_lme_stocks_westmetall
        stk = fetch_lme_stocks_westmetall(refresh=True)
        if not stk.empty:
            log.info("✅ LME stocks: %d точек накоплено, последняя %d т (%s)",
                     len(stk),
                     int(stk["lme_stock_total"].iloc[-1]),
                     stk.index.max().date())
    except Exception as exc:
        log.warning("⚠️  Westmetall LME stocks: %s", exc)

    # 3b. Westmetall LME цены (cash + 3M, 100+ дней истории)
    try:
        from extra_sources import fetch_lme_copper_price
        lme = fetch_lme_copper_price(refresh=True)
        if not lme.empty:
            log.info("✅ LME prices: %d дней истории, последний 3M = %.0f USD/т (%s)",
                     len(lme),
                     float(lme["lme_3m"].iloc[-1]),
                     lme.index.max().date())
    except Exception as exc:
        log.warning("⚠️  Westmetall LME prices: %s", exc)

    # 4. FRED — опционально
    try:
        from extra_sources import fetch_fred_bundle
        fred = fetch_fred_bundle(start_date, refresh=True)
        if not fred.empty:
            log.info("✅ FRED: %d рядов", fred.shape[1])
    except Exception as exc:
        log.warning("⚠️  FRED: %s", exc)

    duration = (dt.datetime.now() - started).total_seconds()
    log.info("Готово за %.1f сек", duration)
    return 0 if base_ok else 1


if __name__ == "__main__":
    sys.exit(main())
