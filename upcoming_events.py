"""
upcoming_events.py — календарь предстоящих событий, влияющих на цену меди.

Источники:
1. **Правила расписания** — для регулярных событий (FOMC, CPI, COT и т.п.).
2. **Курируемый список** — для специальных событий (тарифы Трампа, отчёты компаний, конференции).

Категории:
- rates       — заседания ЦБ по ключевым ставкам
- data        — публикация экономических данных (CPI, PMI, NFP)
- industry    — отраслевые отчёты (ICSG, COT, отчёты компаний)
- policy      — регуляторные действия (тарифы, санкции)
- conference  — отраслевые конференции (LME Week, CRU)

Importance: low / medium / high — влияние на медь.
"""
from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, asdict
from typing import List, Optional

import pandas as pd


@dataclass
class UpcomingEvent:
    date: dt.date
    title: str
    type: str          # rates / data / industry / policy / conference
    importance: str    # low / medium / high
    description: str
    source: Optional[str] = None
    region: str = "🌐"  # 🇺🇸 / 🇪🇺 / 🇨🇳 / 🌐

    @property
    def icon(self) -> str:
        return {
            "rates":      "🏦",
            "data":       "📊",
            "industry":   "⛏️",
            "policy":     "📜",
            "conference": "🎤",
            "earnings":   "💼",
        }.get(self.type, "📅")

    @property
    def color(self) -> str:
        return {
            "low":    "#999999",
            "medium": "#f0a020",
            "high":   "#e44d2e",
        }.get(self.importance, "#666666")

    @property
    def days_until(self) -> int:
        return (self.date - dt.date.today()).days


# ====================================================================
#  Правила расписания
# ====================================================================

# FOMC заседания — известные на год вперёд, публикуются на сайте ФРС.
# Источник: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
FOMC_2026_2027 = [
    dt.date(2026, 1, 28),   # Jan
    dt.date(2026, 3, 18),   # Mar (SEP)
    dt.date(2026, 4, 29),   # Apr/May
    dt.date(2026, 6, 17),   # Jun (SEP)
    dt.date(2026, 7, 29),   # Jul
    dt.date(2026, 9, 16),   # Sep (SEP)
    dt.date(2026, 10, 28),  # Oct/Nov
    dt.date(2026, 12, 16),  # Dec (SEP)
    dt.date(2027, 1, 27),
    dt.date(2027, 3, 17),
    dt.date(2027, 4, 28),
    dt.date(2027, 6, 16),
]

# Заседания ECB (по аналогии)
ECB_2026_2027 = [
    dt.date(2026, 1, 22),
    dt.date(2026, 3, 12),
    dt.date(2026, 4, 16),
    dt.date(2026, 6, 4),
    dt.date(2026, 7, 23),
    dt.date(2026, 9, 10),
    dt.date(2026, 10, 29),
    dt.date(2026, 12, 17),
    dt.date(2027, 1, 21),
]


def _first_business_day(year: int, month: int) -> dt.date:
    """Первый бизнес-день месяца (понедельник-пятница)."""
    d = dt.date(year, month, 1)
    while d.weekday() >= 5:  # 5 = Saturday, 6 = Sunday
        d += dt.timedelta(days=1)
    return d


def _us_cpi_release_date(year: int, month: int) -> dt.date:
    """Примерная дата выхода US CPI — обычно 10-15 число (BLS calendar).
    Берём первый вторник или среду после 9 числа."""
    d = dt.date(year, month, 10)
    while d.weekday() not in (1, 2, 3):  # вт/ср/чт
        d += dt.timedelta(days=1)
    return d


def _generate_rates_events(start: dt.date, end: dt.date) -> List[UpcomingEvent]:
    """ФРС + ЕЦБ заседания."""
    events = []
    for d in FOMC_2026_2027:
        if start <= d <= end:
            events.append(UpcomingEvent(
                date=d, title="FOMC: решение по ставке ФРС",
                type="rates", importance="high",
                description="Заседание FOMC — решение по ключевой ставке США. "
                            "Сильнейший макрофактор для DXY и, через него, для меди.",
                source="https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm",
                region="🇺🇸",
            ))
    for d in ECB_2026_2027:
        if start <= d <= end:
            events.append(UpcomingEvent(
                date=d, title="ECB: решение по ставке",
                type="rates", importance="medium",
                description="Заседание ЕЦБ. Влияет на EUR/USD → DXY → медь.",
                source="https://www.ecb.europa.eu/press/calendars/mgcgc/html/index.en.html",
                region="🇪🇺",
            ))
    return events


def _generate_data_events(start: dt.date, end: dt.date) -> List[UpcomingEvent]:
    """CPI, PMI ISM, Caixin PMI, NFP."""
    events = []
    # Идём по месяцам в окне
    cur = dt.date(start.year, start.month, 1)
    while cur <= end:
        year, month = cur.year, cur.month

        # 1) ISM US Manufacturing PMI — 1-й бизнес-день
        d = _first_business_day(year, month)
        if start <= d <= end:
            events.append(UpcomingEvent(
                date=d, title="ISM Manufacturing PMI (США)",
                type="data", importance="high",
                description="Индекс деловой активности в промышленности США. "
                            "Прямой фактор спроса на медь.",
                source="https://www.ismworld.org/", region="🇺🇸",
            ))

        # 2) Caixin China Manufacturing PMI — также 1-й бизнес-день
        if start <= d <= end:
            events.append(UpcomingEvent(
                date=d, title="Caixin China Manufacturing PMI",
                type="data", importance="high",
                description="Самый чувствительный высокочастотный индикатор "
                            "промышленности Китая. Китай = 55% мирового спроса на медь.",
                source="https://www.pmi.spglobal.com/", region="🇨🇳",
            ))

        # 3) NFP (Non-Farm Payrolls) — первая пятница месяца
        nfp = dt.date(year, month, 1)
        while nfp.weekday() != 4:  # пятница
            nfp += dt.timedelta(days=1)
        if start <= nfp <= end:
            events.append(UpcomingEvent(
                date=nfp, title="Non-Farm Payrolls (NFP)",
                type="data", importance="medium",
                description="Занятость в США (без с/х). Влияет на FOMC и DXY.",
                source="https://www.bls.gov/", region="🇺🇸",
            ))

        # 4) US CPI — примерно 10-12 число
        cpi = _us_cpi_release_date(year, month)
        if start <= cpi <= end:
            events.append(UpcomingEvent(
                date=cpi, title="US CPI (инфляция)",
                type="data", importance="high",
                description="Индекс потребительских цен США. Влияет на решения "
                            "ФРС по ставке, на DXY и на медь как инфляционный hedge.",
                source="https://www.bls.gov/cpi/", region="🇺🇸",
            ))

        # 5) ICSG Monthly Bulletin — обычно к 20 числу (с лагом 2 мес)
        icsg = dt.date(year, month, 20)
        # Сдвинем на бизнес-день, если выходной
        while icsg.weekday() >= 5:
            icsg += dt.timedelta(days=1)
        if start <= icsg <= end:
            events.append(UpcomingEvent(
                date=icsg, title="ICSG Monthly Copper Bulletin",
                type="industry", importance="medium",
                description="Месячный бюллетень ICSG: глобальный баланс "
                            "производства и потребления меди (с лагом 2 мес).",
                source="https://icsg.org/", region="🌐",
            ))

        # Переход к следующему месяцу
        if month == 12:
            cur = dt.date(year + 1, 1, 1)
        else:
            cur = dt.date(year, month + 1, 1)

    return events


def _generate_cot_events(start: dt.date, end: dt.date) -> List[UpcomingEvent]:
    """CFTC COT — каждую пятницу."""
    events = []
    # Идём по пятницам
    d = start
    while d <= end:
        if d.weekday() == 4:  # пятница
            events.append(UpcomingEvent(
                date=d, title="CFTC COT Report",
                type="industry", importance="medium",
                description="Отчёт о позициях хедж-фондов и крупных трейдеров "
                            "на COMEX (по вторник прошлой недели).",
                source="https://www.cftc.gov/MarketReports/CommitmentsofTraders/",
                region="🇺🇸",
            ))
        d += dt.timedelta(days=1)
    return events


# ====================================================================
#  Курируемый список специальных событий
# ====================================================================

CURATED_EVENTS: List[UpcomingEvent] = [
    UpcomingEvent(
        date=dt.date(2026, 6, 9),
        title="Earnings BHP — H1 update",
        type="industry", importance="medium",
        description="Полугодовой отчёт BHP. BHP — оператор Escondida (5% мирового "
                    "производства меди). Прогнозы и комментарии о Чили — важный сигнал.",
        region="🇦🇺",
    ),
    UpcomingEvent(
        date=dt.date(2026, 7, 21),
        title="FCX (Freeport-McMoRan) Q2 earnings",
        type="industry", importance="medium",
        description="Один из крупнейших производителей меди в мире (Grasberg, "
                    "Cerro Verde). Quarterly call часто двигает котировки.",
        region="🇺🇸",
    ),
    UpcomingEvent(
        date=dt.date(2026, 10, 12),
        title="LME Week 2026",
        type="conference", importance="high",
        description="Главное отраслевое событие года в Лондоне. Контракты, "
                    "форвардные кривые, прогнозы. Часто триггер для движений.",
        source="https://www.lme.com/News/Events/LME-Week", region="🇬🇧",
    ),
    UpcomingEvent(
        date=dt.date(2027, 1, 1),
        title="Тариф Трампа на медь: 15%",
        type="policy", importance="high",
        description="Вступает в силу первая ступень тарифа США на медь (15%). "
                    "Может вызвать новое расширение премии COMEX над LME.",
        region="🇺🇸",
    ),
    UpcomingEvent(
        date=dt.date(2028, 1, 1),
        title="Тариф Трампа на медь: 30%",
        type="policy", importance="high",
        description="Вторая ступень тарифа США на медь (30%). Финальная фаза, "
                    "потенциальный новый shock COMEX-LME.",
        region="🇺🇸",
    ),
]


# ====================================================================
#  Основная функция
# ====================================================================

def get_upcoming_events(days_ahead: int = 60,
                        min_importance: str = "low",
                        types: Optional[List[str]] = None) -> List[UpcomingEvent]:
    """Список предстоящих событий в окне days_ahead дней от сегодня."""
    today = dt.date.today()
    end = today + dt.timedelta(days=days_ahead)

    events = (
        _generate_rates_events(today, end)
        + _generate_data_events(today, end)
        + _generate_cot_events(today, end)
        + [e for e in CURATED_EVENTS if today <= e.date <= end]
    )

    # Фильтр по importance
    imp_order = {"low": 0, "medium": 1, "high": 2}
    min_lev = imp_order.get(min_importance, 0)
    events = [e for e in events if imp_order.get(e.importance, 0) >= min_lev]

    if types:
        events = [e for e in events if e.type in types]

    return sorted(events, key=lambda e: e.date)


def get_top_events(n: int = 5, days_ahead: int = 30) -> List[UpcomingEvent]:
    """ТОП-N самых важных предстоящих событий.
    Сортировка: сначала high importance, затем medium, затем low.
    Внутри одного уровня — по дате (ближайшие первыми).
    """
    events = get_upcoming_events(days_ahead=days_ahead, min_importance="low")
    imp_order = {"high": 3, "medium": 2, "low": 1}
    events.sort(key=lambda e: (-imp_order.get(e.importance, 0), e.date))
    return events[:n]


def events_to_dataframe(events: List[UpcomingEvent]) -> pd.DataFrame:
    """Превратить список в DataFrame для Streamlit."""
    if not events:
        return pd.DataFrame(columns=["Дата", "Дней", "Регион", "Тип",
                                       "Важность", "Событие", "Описание"])
    return pd.DataFrame([{
        "Дата": e.date,
        "Дней": e.days_until,
        "Регион": e.region,
        "Тип": e.icon + " " + e.type,
        "Важность": e.importance,
        "Событие": e.title,
        "Описание": e.description,
        "Источник": e.source or "",
    } for e in events])


if __name__ == "__main__":
    print("=== ТОП-5 ближайших событий ===")
    for e in get_top_events(5, 30):
        print(f"  {e.date}  [{e.importance:6s}] {e.icon} {e.region} {e.title}  ({e.days_until:+d} дн.)")

    print(f"\n=== Все события на 30 дней вперёд (min_importance=medium) ===")
    for e in get_upcoming_events(30, "medium"):
        print(f"  {e.date}  [{e.importance:6s}] {e.icon} {e.title}")
