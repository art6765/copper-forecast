"""
china.py — ручной ввод ключевых китайских индикаторов спроса на медь.

Бесплатные китайские данные (премия Яншань, запасы SHFE) недоступны для
автоматического сбора из инфраструктуры проекта: биржа SHFE блокирует ботов,
а премия Яншань на metal.com подгружается JavaScript'ом. Поэтому ключевой
сигнал — премию Яншань — закупщик вводит вручную, сверяясь с бесплатными
источниками. Значение сохраняется между сессиями (data/china_inputs.json).

Премия Яншань (Yangshan copper premium) — надбавка к LME за импорт катода в Китай.
Высокая/растущая премия = сильный импортный спрос крупнейшего потребителя
(~60% мирового рынка) = поддержка цены, риск роста. Низкая/падающая = слабый спрос.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, Optional

STATE = Path(__file__).resolve().parent / "data" / "china_inputs.json"

# Бесплатные источники для ручной сверки (открываются глазами)
SOURCES = {
    "Премия Яншань (metal.com)": "https://www.metal.com/copper/201211190003",
    "Запасы SHFE": "https://metalcharts.org/shfe/copper",
    "Импорт меди Китаем": "https://tradingeconomics.com/china/imports/copper",
}

TRENDS = ["—", "растёт", "стабильна", "падает"]


def load_inputs() -> Dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save_inputs(data: Dict) -> None:
    try:
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except Exception:
        pass


def yangshan_signal(premium: Optional[float], trend: str = "—") -> Optional[Dict]:
    """Интерпретация премии Яншань для закупщика. None, если не задана.

    Тон в палитре факторов: wait (красный) = тревога/риск роста (сильный спрос),
    ok (зелёный) = спокойно (слабый спрос). Исторический диапазон ~ $30–150/т.
    """
    if not premium or premium <= 0:
        return None
    if premium >= 90:
        tone, lvl = "wait", "высокая"
        note = "Сильный импортный спрос Китая — поддержка цены, риск роста."
    elif premium >= 50:
        tone, lvl = "warn", "умеренная"
        note = "Спрос Китая средний — нейтрально-поддерживающе."
    else:
        tone, lvl = "ok", "низкая"
        note = "Слабый импортный спрос Китая — давление на цену вниз."
    if trend == "растёт":
        note += " Тренд вверх усиливает сигнал."
    elif trend == "падает":
        note += " Тренд вниз ослабляет спрос."
    return {"premium": float(premium), "trend": trend, "level": lvl,
            "tone": tone, "note": note}
