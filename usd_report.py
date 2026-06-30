"""
usd_report.py — ИИ-объяснение прогноза курса доллара (USD/RUB) простыми словами.

Аналог decision_report.py, но фокус — на КУРСЕ рубля, а не на меди. Собирает
текущую картину по курсу (прогноз ЦБ-курса на горизонты, коридор, вероятность
роста) и драйверы рубля (нефть Brent, индекс доллара DXY, ключевая ставка ЦБ,
carry = дифференциал ставок ЦБ−ФРС) и просит языковую модель объяснить, почему
система видит такой вектор курса и что это значит для рублёвой цены закупки.

Логика закупщика: рост курса доллара = рубль слабее = медь в рублях дороже.

Ключ — тот же DEEPSEEK_API_KEY (.env), что и у брифинга/отчёта по меди.
Зависимости: brief (urllib). Новых пакетов нет.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import pandas as pd

import brief

SYSTEM_PROMPT = (
    "Ты — валютный аналитик в отделе закупок промышленного холдинга. Твоя задача "
    "— объяснить закупщику ПРОСТЫМ, человеческим языком, почему прогнозная система "
    "видит именно такой вектор курса доллара к рублю (USD/RUB) и что это значит "
    "для цены закупки меди в рублях.\n"
    "Строгие правила:\n"
    "1. Опирайся ТОЛЬКО на переданные числа и драйверы. Не выдумывай данные, "
    "события и причины, которых нет во входных данных.\n"
    "2. Пиши по-русски, коротко и по делу, без биржевого жаргона. Объясняй так, "
    "будто человек не разбирается в валютном рынке.\n"
    "3. Логика ЗАКУПЩИКА: рост курса доллара = рубль слабеет = медь в рублях "
    "дорожает (плохо для закупки); падение курса = рубль крепнет = медь дешевеет.\n"
    "4. Главные драйверы рубля объясняй простыми связями: дорогая нефть Brent → "
    "рубль крепче; сильный доллар в мире (DXY растёт) → рубль слабее; высокая "
    "ключевая ставка ЦБ и высокий carry (разница ставок ЦБ и ФРС) → рубль крепче.\n"
    "5. Помни: официальный курс ЦБ управляемый и сглаженный, вокруг "
    "политических/санкционных шоков прогноз курса менее точен. Не давай "
    "инвестиционных советов и гарантий — это ориентир, решение за человеком."
)

OUTPUT_FORMAT = """Составь короткий отчёт СТРОГО в этом формате (Markdown):

## 📋 Вывод
[1–2 предложения: куда идёт курс на выбранный срок и что это значит для рублёвой цены меди — рубль слабеет (медь дорожает) или крепнет (дешевеет).]

## 🔍 Почему так
[3–5 пунктов простым языком: какие драйверы тянут рубль — нефть Brent, индекс доллара DXY, ключевая ставка ЦБ, carry, режим. Каждый пункт — одно предложение со ссылкой на конкретные числа из данных.]

## 💱 Курс по срокам
[Что с курсом на выбранный срок и в целом по горизонтам: назови прогнозный курс и коридор (p10–p90), поясни, что коридор значит.]

## ⚠️ Риски и оговорки
[1–2 предложения: официальный курс ЦБ управляемый/сглаженный, что может сломать прогноз (санкции, решения ЦБ, резкое движение нефти), насколько широк разброс.]"""


def usd_drivers(raw: pd.DataFrame) -> List[Dict]:
    """Текущие значения драйверов рубля + краткосрочный тренд — для отчёта.

    Возвращает список {title, value} с человекочитаемыми числами. Берёт только
    то, что реально есть в данных (колонки пропускаются, если их нет).
    """
    out: List[Dict] = []

    def _chg(col: str, days: int = 20) -> Optional[float]:
        if col not in raw.columns:
            return None
        s = raw[col].dropna()
        if len(s) <= days:
            return None
        prev = float(s.iloc[-days - 1])
        if prev == 0:
            return None
        return (float(s.iloc[-1]) / prev - 1) * 100

    if "brent" in raw.columns and raw["brent"].notna().any():
        last = float(raw["brent"].dropna().iloc[-1])
        ch = _chg("brent")
        out.append({"title": "Нефть Brent",
                    "value": f"{last:,.1f} $/барр"
                             + (f" ({ch:+.1f}% за месяц)" if ch is not None else "")})
    if "dxy" in raw.columns and raw["dxy"].notna().any():
        last = float(raw["dxy"].dropna().iloc[-1])
        ch = _chg("dxy")
        out.append({"title": "Индекс доллара DXY",
                    "value": f"{last:,.1f}"
                             + (f" ({ch:+.1f}% за месяц)" if ch is not None else "")})
    if "cbr_key_rate" in raw.columns and raw["cbr_key_rate"].notna().any():
        kr = float(raw["cbr_key_rate"].dropna().iloc[-1])
        out.append({"title": "Ключевая ставка ЦБ РФ", "value": f"{kr:.2f}% годовых"})
        if "fred_fedfunds" in raw.columns and raw["fred_fedfunds"].notna().any():
            ff = float(raw["fred_fedfunds"].dropna().iloc[-1])
            out.append({"title": "Carry (ставка ЦБ − ставка ФРС)",
                        "value": f"{kr - ff:+.2f} п.п."})
    return out


def _fmt_drivers(drivers: Optional[List[Dict]]) -> str:
    if not drivers:
        return "(драйверы не переданы)"
    return "\n".join(f"- {d.get('title', '')}: {d.get('value', '')}" for d in drivers)


def _fmt_horizons(horizons: Optional[List[Dict]]) -> str:
    if not horizons:
        return "(прогнозы по горизонтам не переданы)"
    lines = []
    for h in horizons:
        parts = [f"{h.get('label', '')}: курс {h.get('fx_fore', 0):.2f} ₽/$"]
        if h.get("change_pct") is not None:
            parts.append(f"({h['change_pct']:+.1f}%)")
        if h.get("p10") and h.get("p90"):
            parts.append(f"коридор {h['p10']:.2f}–{h['p90']:.2f}")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


def build_messages(context: Dict) -> List[Dict]:
    """Собрать system + user сообщения из контекста прогноза курса."""
    c = context
    chosen = (
        f"Выбранный срок планирования: {c.get('horizon_label', '—')} "
        f"({c.get('horizon_sub', '')}).\n"
        f"Прогноз курса доллара: {c.get('fx_fore', 0):.2f} ₽/$ "
        f"({c.get('fx_change', 0):+.1f}% к текущему), "
        f"коридор {c.get('fx_p10', 0):.2f}–{c.get('fx_p90', 0):.2f} ₽/$, "
        f"вероятность роста курса {c.get('fx_prob_up', 0):.0f}%.\n"
    )
    if c.get("med_rub_change") is not None:
        chosen += (f"Влияние на медь в рублях: при таком курсе рублёвая цена меди "
                   f"меняется примерно на {c['med_rub_change']:+.1f}% за счёт валюты.\n")

    user = (
        f"Дата данных: {c.get('as_of', '—')}.\n"
        f"Текущий курс доллара ЦБ РФ: {c.get('current_usdrub', 0):.2f} ₽/$.\n"
        f"Режим рынка: {c.get('regime', '—')}.\n\n"
        f"{chosen}\n"
        f"Драйверы рубля, которые учитывает система:\n"
        f"{_fmt_drivers(c.get('drivers'))}\n\n"
        f"Прогноз курса по всем горизонтам:\n{_fmt_horizons(c.get('all_horizons'))}\n\n"
        f"{OUTPUT_FORMAT}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


def has_api_key() -> bool:
    """Есть ли ключ DeepSeek для генерации отчёта."""
    return bool(brief.get_api_key())


def generate_report(context: Dict, temperature: float = 0.4,
                    max_tokens: int = 1400) -> str:
    """Сгенерировать markdown-отчёт по курсу. Бросает RuntimeError, если ключ
    не задан или API недоступен."""
    messages = build_messages(context)
    return brief.chat_completion(messages, temperature=temperature,
                                 max_tokens=max_tokens)
