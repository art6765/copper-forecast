"""
carry.py — сигнал форвардной кривой LME (контанго / бэквордация).

Спред между ценой спот (cash) и 3-месячным форвардом (3M) — прямой индикатор
физического баланса меди и ответ на вечный вопрос закупщика «брать сейчас и
хранить или подождать»:

  cash > 3M  → БЭКВОРДАЦИЯ: спот дороже форварда. Рынок платит премию за
               немедленную поставку → дефицит здесь и сейчас → цена склонна расти,
               держать запас выгодно. Сигнал: брать сейчас, не тянуть.
  cash < 3M  → КОНТАНГО: форвард дороже спота. Запасы комфортны, рынок спокоен;
               стоимость хранения заложена в форвард → копить впрок невыгодно.

Данные — lme_cash и lme_3m из data_loader (Westmetall). Новых источников нет.
"""
from __future__ import annotations

from typing import Dict, Optional

import numpy as np
import pandas as pd

# Порог острого дефицита (бэквордация), USD/т — ориентир из интервью с экспертом.
STRONG_BACKWARDATION = 30.0


def carry_signal(raw: pd.DataFrame) -> Optional[Dict]:
    """Состояние форвардной кривой LME по последним cash/3M.

    Возвращает dict {state, spread, spread_pct, cash, m3, tone, note} или None,
    если данных нет. tone — в палитре факторов (ok/warn/wait).
    """
    if "lme_cash" not in raw.columns or "lme_3m" not in raw.columns:
        return None
    both = raw[["lme_cash", "lme_3m"]].dropna()
    if both.empty:
        return None
    cash = float(both["lme_cash"].iloc[-1])
    m3 = float(both["lme_3m"].iloc[-1])
    if m3 <= 0:
        return None
    spread = cash - m3
    spread_pct = spread / m3 * 100

    if spread >= STRONG_BACKWARDATION:
        state, tone = "Бэквордация (сильная)", "wait"
        note = ("Спот заметно дороже форварда — острый дефицит. Рынок платит за "
                "немедленную поставку. Брать сейчас, не откладывать.")
    elif spread > 2:
        state, tone = "Бэквордация", "warn"
        note = ("Спот дороже форварда — рынок напряжён, запасы тают. Закупаться "
                "ближе к сроку, без больших пауз; держать запас выгодно.")
    elif spread < -2:
        state, tone = "Контанго", "ok"
        note = ("Форвард дороже спота — запасы комфортны, рынок спокоен. Спешки нет; "
                "копить большой запас впрок невыгодно (хранение заложено в цену).")
    else:
        state, tone = "Плоская кривая", "warn"
        note = ("Спот и форвард почти равны — баланс нейтральный, явного сигнала "
                "дефицита или профицита нет.")

    return {"state": state, "spread": spread, "spread_pct": spread_pct,
            "cash": cash, "m3": m3, "tone": tone, "note": note}


def spread_forecast(raw: pd.DataFrame, lookback: int = 20,
                    horizon: int = 10) -> Optional[Dict]:
    """Прогноз динамики спреда cash − 3M: куда движется напряжение рынка.

    Спред — шумный краткосрочный ряд, поэтому прогноз простой и честный: тренд
    (наклон линейной регрессии за lookback дней) с усадкой 0.5 на horizon дней
    вперёд (спред склонен возвращаться к среднему). Расширение бэквордации = дефицит
    нарастает (поддержка цены), сужение = напряжение спадает.

    Возвращает {current, forecast, change, direction, tone, note} или None.
    """
    if "lme_cash" not in raw.columns or "lme_3m" not in raw.columns:
        return None
    sp = (raw["lme_cash"] - raw["lme_3m"]).dropna().tail(lookback)
    if len(sp) < 5:
        return None
    x = np.arange(len(sp), dtype=float)
    slope = float(np.polyfit(x, sp.values, 1)[0])   # USD/т в день
    current = float(sp.iloc[-1])
    forecast = current + slope * horizon * 0.5      # усадка тренда (mean-reversion)
    change = forecast - current

    if change > 5:
        direction, tone = "к бэквордации", "wait"
        note = "Спред растёт к дефициту — поддержка цены усиливается."
    elif change < -5:
        direction, tone = "к контанго", "ok"
        note = "Спред уходит в контанго — давление дефицита спадает, профицит нарастает."
    else:
        direction, tone = "без динамики", "warn"
        note = "Спред стабилен."

    return {"current": current, "forecast": forecast, "change": change,
            "horizon": horizon, "direction": direction, "tone": tone, "note": note}


if __name__ == "__main__":
    import logging
    import datetime as dt
    logging.basicConfig(level=logging.ERROR)
    from data_loader import load_all
    start = (dt.date.today() - dt.timedelta(days=200)).strftime("%Y-%m-%d")
    raw = load_all(start=start, include_cot=False, include_fred=False)
    print(carry_signal(raw))
    print(spread_forecast(raw))
