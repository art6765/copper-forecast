"""
decision_report.py — ИИ-объяснение прогноза для закупщика.

Собирает текущую картину (вердикт, прогнозы меди и курса доллара, факторы,
режим рынка) в структурированный контекст и просит языковую модель (DeepSeek,
через готовый клиент brief.chat_completion) объяснить ПРОСТЫМИ СЛОВАМИ, почему
система видит такой вектор изменения котировок и что это значит для закупки.

Ключ берётся из того же источника, что и брифинг новостей (DEEPSEEK_API_KEY
в .env). Если ключа нет — generate_report бросает понятную ошибку.

Зависимости: только brief (urllib). Новых пакетов нет.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import brief

SYSTEM_PROMPT = (
    "Ты — старший аналитик рынка меди в отделе закупок промышленного холдинга. "
    "Твоя задача — объяснить закупщику ПРОСТЫМ, человеческим языком, почему "
    "прогнозная система видит именно такой вектор изменения цены меди и курса "
    "доллара, и что это значит для закупки.\n"
    "Строгие правила:\n"
    "1. Опирайся ТОЛЬКО на переданные числа и факторы. Не выдумывай данные, "
    "события, цифры и причины, которых нет во входных данных.\n"
    "2. Пиши по-русски, коротко и по делу, без воды и без биржевого жаргона. "
    "Представь, что объясняешь человеку, который не разбирается в трейдинге.\n"
    "3. Помни логику ЗАКУПЩИКА: рост цены — это плохо (надо успеть купить "
    "дешевле), падение — можно подождать. Рост курса доллара удорожает медь "
    "в рублях.\n"
    "4. Не давай инвестиционных советов и гарантий — это ориентир, а не приказ. "
    "Решение всегда за человеком."
)

OUTPUT_FORMAT = """Составь короткий отчёт СТРОГО в этом формате (Markdown):

## 📋 Вывод
[1–2 предложения: что происходит с ценой и что делать закупщику — покупать сейчас, дробить или подождать.]

## 🔍 Почему так
[3–5 пунктов простым языком: какие факторы тянут цену вверх или вниз — запасы, доллар, спекулянты, премия, режим рынка. Каждый пункт — одно предложение, со ссылкой на конкретные числа из данных.]

## 💰 Цена и рубли
[Что с ценой в долларах и в рублях на выбранный срок, с учётом прогноза курса. Назови диапазон (коридор) и поясни, что он значит.]

## ⚠️ Риски и оговорки
[1–2 предложения: насколько широк разброс, что может сломать прогноз, на что обратить внимание.]"""


def _fmt_factors(factors: Optional[List[Dict]]) -> str:
    if not factors:
        return "(факторы не переданы)"
    tone_ru = {"ok": "спокойно", "warn": "внимание", "wait": "риск"}
    lines = []
    for f in factors:
        tag = tone_ru.get(f.get("tone", ""), "")
        lines.append(f"- {f.get('title', '')}: {f.get('value', '')}"
                     + (f" [{tag}]" if tag else ""))
    return "\n".join(lines)


def _fmt_horizons(horizons: Optional[List[Dict]]) -> str:
    if not horizons:
        return "(прогнозы по горизонтам не переданы)"
    lines = []
    for h in horizons:
        parts = [f"{h.get('label', '')}: медь {h.get('med_usd_t', 0):,.0f} USD/т"]
        if h.get("change_pct") is not None:
            parts.append(f"({h['change_pct']:+.1f}%)")
        if h.get("med_rub"):
            parts.append(f"≈ {h['med_rub']:,.0f} ₽/т")
        if h.get("fx_fore"):
            parts.append(f"курс {h['fx_fore']:.2f} ₽/$")
        lines.append("- " + " ".join(parts))
    return "\n".join(lines)


def build_messages(context: Dict) -> List[Dict]:
    """Собрать system + user сообщения из контекста прогноза."""
    c = context
    chosen = (
        f"Выбранный срок планирования: {c.get('horizon_label', '—')} "
        f"({c.get('horizon_sub', '')}).\n"
        f"Вердикт системы: {c.get('verdict', '—')} "
        f"({c.get('verdict_ru', '')}).\n"
        f"Прогноз цены меди: {c.get('med_usd_t', 0):,.0f} USD/т "
        f"({c.get('change_pct', 0):+.1f}% к текущей), "
        f"коридор {c.get('p10', 0):,.0f}–{c.get('p90', 0):,.0f} USD/т, "
        f"вероятность роста {c.get('prob_up', 0):.0f}%.\n"
    )
    if c.get("med_rub"):
        chosen += (f"В рублях по прогнозному курсу: ≈ {c['med_rub']:,.0f} ₽/т "
                   f"(курс {c.get('fx_fore', 0):.2f} ₽/$, "
                   f"изменение курса {c.get('fx_change', 0):+.1f}%).\n")

    user = (
        f"Дата данных: {c.get('as_of', '—')}.\n"
        f"Рынок-ориентир: {c.get('unit', '—')}.\n"
        f"Текущая цена меди (спот): {c.get('spot_usd_t', 0):,.0f} USD/т.\n"
        f"Текущий курс доллара ЦБ РФ: {c.get('current_usdrub', 0):.2f} ₽/$.\n"
        f"Режим рынка: {c.get('regime', '—')}.\n\n"
        f"{chosen}\n"
        f"Факторы, которые учитывает система:\n{_fmt_factors(c.get('factors'))}\n\n"
        f"Прогноз по всем горизонтам:\n{_fmt_horizons(c.get('all_horizons'))}\n\n"
        f"Краткое пояснение системы (для опоры): {c.get('verdict_why', '')}\n\n"
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
    """Сгенерировать markdown-отчёт по контексту прогноза. Бросает RuntimeError,
    если ключ не задан или API недоступен."""
    messages = build_messages(context)
    return brief.chat_completion(messages, temperature=temperature,
                                 max_tokens=max_tokens)
