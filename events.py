"""
events.py — каталог ключевых событий, влиявших на цену меди в 2020-2026.

Все события собраны из аналитической записки (compass_artifact_*) и
открытых источников (CSIS, Reuters, MINING.COM, ICSG, IEA).

Типы:
- supply_shock    — шок предложения (забастовка, авария, закрытие)
- demand_shock    — шок спроса (рецессия, стимул)
- policy          — регуляторные/тарифные действия
- macro           — макроэкономические события (FOMC, инфляция, валюты)
- geopolitical    — геополитика (война, санкции)
- structural      — структурные сдвиги (EV-бум, энергопереход)

Severity:
- low      — локальный, ограниченный эффект
- medium   — заметное движение цены (1-3%)
- high     — крупное движение (>3%) или сдвиг режима
- critical — структурный шок (>10% движение, разворот тренда)
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import List, Optional

import pandas as pd


@dataclass
class CopperEvent:
    date: dt.date
    title: str
    type: str
    severity: str          # low / medium / high / critical
    description: str
    url: Optional[str] = None
    supply_impact_kt: Optional[float] = None  # выбывшая мощность, тыс. т/год
    price_impact_pct: Optional[float] = None  # ориентир движения цены

    @property
    def color(self) -> str:
        return {
            "low": "#999999",
            "medium": "#f0a020",
            "high": "#e44d2e",
            "critical": "#b21f1f",
        }.get(self.severity, "#666666")

    @property
    def icon(self) -> str:
        return {
            "supply_shock":  "⛏️",
            "demand_shock":  "🏭",
            "policy":        "📜",
            "macro":         "💱",
            "geopolitical":  "🌍",
            "structural":    "🔄",
        }.get(self.type, "📌")


# --------------------------------------------------------------------
#  Каталог исторических событий
# --------------------------------------------------------------------

EVENTS: List[CopperEvent] = [
    # =================== 2020 ===================
    CopperEvent(
        date=dt.date(2020, 3, 23),
        title="COVID-19: исторический минимум",
        type="demand_shock", severity="critical",
        description=(
            "LME 3M $4 617,50/т — минимум за 4 года. Падение на 26.2% от Q1 2020. "
            "Глобальная рецессия, локдауны, обвал промышленного спроса."
        ),
        price_impact_pct=-26.2,
    ),
    CopperEvent(
        date=dt.date(2020, 3, 1),
        title="Локдауны в Перу",
        type="supply_shock", severity="high",
        description=(
            "Карантин остановил работу на крупнейших рудниках Перу "
            "(Antamina, Cerro Verde, Las Bambas). Удалено ~10% мирового предложения."
        ),
        supply_impact_kt=200,
    ),
    CopperEvent(
        date=dt.date(2020, 4, 1),
        title="Caixin PMI восстанавливается к 50",
        type="demand_shock", severity="high",
        description=(
            "Китайский PMI вышел из контракции, сигнал V-образного восстановления. "
            "Триггер для разворота цены вверх."
        ),
    ),

    # =================== 2021 ===================
    CopperEvent(
        date=dt.date(2021, 5, 10),
        title="LME 3M преодолевает $10 000/т",
        type="demand_shock", severity="critical",
        description=(
            "Впервые в истории цена меди превысила $10 000/т. "
            "Драйверы: глобальный фискально-монетарный стимул, дефицит после локдаунов в Перу/Чили."
        ),
        price_impact_pct=+30.0,
    ),
    CopperEvent(
        date=dt.date(2021, 12, 9),
        title="Дефолт Evergrande",
        type="demand_shock", severity="critical",
        description=(
            "Fitch объявил Evergrande в состоянии restricted default. "
            "Старт волны дефолтов девелоперов Китая → длительная стагнация спроса со стороны строительства "
            "(~10% мирового потребления меди)."
        ),
        price_impact_pct=-5.0,
    ),

    # =================== 2022 ===================
    CopperEvent(
        date=dt.date(2022, 3, 4),
        title="Пик после вторжения РФ в Украину",
        type="geopolitical", severity="critical",
        description=(
            "COMEX HG $5.02/lb — исторический пик. Реакция на войну, опасения санкций "
            "против российских металлов, спекулятивный спрос."
        ),
        price_impact_pct=+8.0,
    ),
    CopperEvent(
        date=dt.date(2022, 3, 16),
        title="ФРС: первое повышение ставки в цикле",
        type="macro", severity="high",
        description=(
            "ФРС подняла ставку с 0-0.25% до 0.25-0.5%. Старт самого агрессивного "
            "цикла ужесточения с 1980-х → DXY ралли, давление на медь."
        ),
    ),
    CopperEvent(
        date=dt.date(2022, 7, 14),
        title="Минимум 2022: COMEX ниже $3.20/lb",
        type="demand_shock", severity="high",
        description=(
            "Опасения рецессии в США + китайские локдауны Covid Zero. "
            "Цена упала на 35% от мартовского пика."
        ),
        price_impact_pct=-35.0,
    ),

    # =================== 2023 ===================
    CopperEvent(
        date=dt.date(2023, 8, 14),
        title="Country Garden пропускает выплаты",
        type="demand_shock", severity="high",
        description=(
            "Второй крупнейший девелопер Китая объявил о пропуске выплат по облигациям. "
            "Усугубление кризиса недвижимости, давление на спрос."
        ),
    ),
    CopperEvent(
        date=dt.date(2023, 11, 28),
        title="Cobre Panamá: суд закрывает рудник",
        type="supply_shock", severity="critical",
        description=(
            "Верховный суд Панамы признал контракт First Quantum неконституционным. "
            "Закрытие мины (330 863 т Cu в 2023, ~1.5% мирового предложения). "
            "Подкрепил bull-кейс на 2024."
        ),
        supply_impact_kt=331,
        price_impact_pct=+3.0,
    ),

    # =================== 2024 ===================
    CopperEvent(
        date=dt.date(2024, 3, 11),
        title="Китай: ограничения на выплавку из-за низких TC/RC",
        type="supply_shock", severity="high",
        description=(
            "Китайские плавильные мощности заявили о сокращении производства из-за обвала "
            "TC/RC (treatment/refining charges). Спот TC ушёл в отрицательную зону."
        ),
    ),
    CopperEvent(
        date=dt.date(2024, 5, 20),
        title="Исторический пик COMEX $5.20/lb",
        type="demand_shock", severity="critical",
        description=(
            "COMEX HG достиг $5.20/lb ≈ $11 464/т. Кульминация ралли на фоне Cobre Panamá, "
            "дефицита концентрата и short-squeeze на COMEX (премия LME 8%)."
        ),
        price_impact_pct=+25.0,
    ),
    CopperEvent(
        date=dt.date(2024, 8, 13),
        title="Забастовка Escondida (BHP, Чили)",
        type="supply_shock", severity="critical",
        description=(
            "2 400 рабочих профсоюза №1 BHP остановили крупнейшую в мире медную мину "
            "(1.1 млн т в 2023, ~5% мирового производства). "
            "Goldman оценивал EBITDA-эффект в $16 млн/день."
        ),
        supply_impact_kt=1100,
        price_impact_pct=+4.0,
    ),
    CopperEvent(
        date=dt.date(2024, 9, 18),
        title="ФРС: первое снижение ставки на 50 б.п.",
        type="macro", severity="medium",
        description=(
            "ФРС начала цикл снижения ставок (с 5.25-5.5% до 4.75-5.0%). "
            "DXY ослаб, поддержка цен на товарные активы."
        ),
    ),
    CopperEvent(
        date=dt.date(2024, 12, 6),
        title="TC/RC benchmark 2025: $21,25/т (-73% г/г)",
        type="supply_shock", severity="high",
        description=(
            "Antofagasta/Jiangxi Copper согласовали бенчмарк TC/RC на 2025 на уровне $21,25/т "
            "против $80/т в 2024. Сигнал жесткого дефицита концентрата."
        ),
    ),

    # =================== 2025 ===================
    CopperEvent(
        date=dt.date(2025, 7, 9),
        title="Трамп: 50% тариф на медь (анонс)",
        type="policy", severity="critical",
        description=(
            "Президент США объявил о намерении ввести 50% тариф на медь. "
            "Премия COMEX над LME расширилась до 30% против исторических 0.5%. "
            "Краткосрочно — арбитражный поток меди в США."
        ),
        price_impact_pct=+12.0,
    ),
    CopperEvent(
        date=dt.date(2025, 7, 30),
        title="Финальные условия тарифов: 15% с 2027 / 30% с 2028",
        type="policy", severity="high",
        description=(
            "Рафинированная медь временно исключена из тарифов. "
            "Прояснение деталей вызвало резкий коллапс премий COMEX над LME и обвал американских цен."
        ),
        price_impact_pct=-15.0,
    ),
    CopperEvent(
        date=dt.date(2025, 8, 1),
        title="LME-COMEX арбитражное обнуление",
        type="policy", severity="critical",
        description=(
            "После публикации деталей тарифов премия COMEX/LME упала с 30% к 5% за неделю. "
            "Самое сильное недельное движение в новейшей истории меди."
        ),
        price_impact_pct=-25.0,
    ),
    CopperEvent(
        date=dt.date(2025, 11, 5),
        title="Caixin China PMI падает до 49.9",
        type="demand_shock", severity="medium",
        description=(
            "Возврат китайского PMI в зону контракции после нескольких месяцев экспансии. "
            "Транслировался в коррекцию цены на 4%."
        ),
        price_impact_pct=-4.0,
    ),

    # =================== 2026 ===================
    CopperEvent(
        date=dt.date(2026, 2, 15),
        title="ICSG: профицит 380 кт в 2025 (preliminary)",
        type="supply_shock", severity="medium",
        description=(
            "ICSG Monthly Bulletin: профицит рафинированной меди 380 000 т в 2025 "
            "(против дефицита 69 000 т в 2024). Опережающий ввод плавильных мощностей в Китае и ДРК."
        ),
    ),
    CopperEvent(
        date=dt.date(2026, 4, 10),
        title="CRU: спот TC/RC −$124/-12.4¢",
        type="supply_shock", severity="high",
        description=(
            "Спот TC/RC ушли на исторический минимум — отрицательные значения. "
            "Расхождение с профицитом катода: жесткий дефицит концентрата при избытке плавильных мощностей."
        ),
    ),

    # =================== Структурные ===================
    CopperEvent(
        date=dt.date(2024, 5, 14),
        title="IEA Global EV Outlook: 17 млн EV в 2024",
        type="structural", severity="medium",
        description=(
            "Электромобили достигли 20% доли мировых продаж. "
            "Структурный спрос на медь: ~70 кг/BEV vs ~24 кг в ICE. "
            "Поддержка bull-кейса 2025-2035."
        ),
    ),
    CopperEvent(
        date=dt.date(2023, 10, 1),
        title="AI data center boom: спрос на медь от грид-инфраструктуры",
        type="structural", severity="medium",
        description=(
            "S&P Global: AI-датацентры требуют масштабной grid-инфраструктуры. "
            "92% net generating capacity additions в 2024 — возобновляемые источники."
        ),
    ),
]


# --------------------------------------------------------------------
#  Удобные функции для работы
# --------------------------------------------------------------------

def events_in_range(start: dt.date, end: dt.date,
                    min_severity: str = "low",
                    types: Optional[List[str]] = None) -> List[CopperEvent]:
    """События в диапазоне дат, с фильтром по severity/типу."""
    sev_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
    min_lev = sev_order.get(min_severity, 0)
    out = []
    for e in EVENTS:
        if not (start <= e.date <= end):
            continue
        if sev_order.get(e.severity, 0) < min_lev:
            continue
        if types and e.type not in types:
            continue
        out.append(e)
    return sorted(out, key=lambda e: e.date)


def events_to_dataframe(events: Optional[List[CopperEvent]] = None) -> pd.DataFrame:
    """Превратить список событий в DataFrame для Streamlit."""
    if events is None:
        events = EVENTS
    return pd.DataFrame([{
        "Дата": e.date,
        "Тип": e.type,
        "Severity": e.severity,
        "Заголовок": e.icon + " " + e.title,
        "Описание": e.description,
        "Δ цены, %": e.price_impact_pct,
        "Supply impact, кт": e.supply_impact_kt,
    } for e in events])


def nearest_event(target: dt.date, window_days: int = 14) -> Optional[CopperEvent]:
    """Найти ближайшее событие в окне ±window_days от даты."""
    best = None
    best_delta = window_days + 1
    for e in EVENTS:
        delta = abs((e.date - target).days)
        if delta < best_delta:
            best_delta = delta
            best = e
    return best if best_delta <= window_days else None


if __name__ == "__main__":
    print(f"Всего событий в каталоге: {len(EVENTS)}\n")
    df = events_to_dataframe()
    print(df[["Дата", "Severity", "Заголовок"]].to_string(index=False))
    print()
    print("--- Только critical с 2024 года ---")
    crit = events_in_range(dt.date(2024, 1, 1), dt.date(2026, 12, 31),
                            min_severity="critical")
    for e in crit:
        print(f"  {e.date}  {e.icon} {e.title}  ({e.severity})")
