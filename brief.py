"""
brief.py — ежедневный ИИ-брифинг по рынку меди.

Берёт свежие заголовки (news.fetch_all_news) и отдаёт их LLM (по умолчанию
DeepSeek) с просьбой составить краткий структурированный брифинг для отдела
закупок. Заменяет примитивный VADER-сентимент умной курацией: модель сама
отбирает значимое, связывает события и объясняет, что важно для цены меди.

Провайдер-агностичность — любой OpenAI-совместимый chat API. Настройка через env:
    BRIEF_API_KEY  (или DEEPSEEK_API_KEY) — ключ
    BRIEF_LLM_BASE_URL                    — по умолчанию https://api.deepseek.com
    BRIEF_LLM_MODEL                       — по умолчанию deepseek-chat

Ключ НИКОГДА не хранится в коде. Читается из переменных окружения или из файла
.env рядом с модулем (строки KEY=VALUE) — .env добавлен в .gitignore.

Зависимости — только стандартная библиотека (urllib) + pandas. Новых пакетов нет.

CLI (для cron):  python brief.py   → сгенерировать и сохранить брифинг.
"""
from __future__ import annotations

import datetime as dt
import json
import logging
import os
import ssl
from pathlib import Path
from typing import Dict, List, Optional
from urllib.request import Request, urlopen

import pandas as pd

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
BRIEF_DIR = BASE_DIR / "data" / "briefings"

DEFAULT_BASE_URL = "https://api.deepseek.com"
DEFAULT_MODEL = "deepseek-chat"


# ---------------------------------------------------------------------------
#  Конфигурация и ключ
# ---------------------------------------------------------------------------

def _load_env_file() -> None:
    """Подхватить .env рядом с модулем (KEY=VALUE), не перезаписывая os.environ."""
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for line in env_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except Exception as exc:
        logger.warning("Не удалось прочитать .env: %s", exc)


def get_api_key() -> Optional[str]:
    """Ключ из BRIEF_API_KEY или DEEPSEEK_API_KEY (env или .env)."""
    _load_env_file()
    return os.environ.get("BRIEF_API_KEY") or os.environ.get("DEEPSEEK_API_KEY")


def _base_url() -> str:
    _load_env_file()
    return os.environ.get("BRIEF_LLM_BASE_URL", DEFAULT_BASE_URL).rstrip("/")


def _model() -> str:
    _load_env_file()
    return os.environ.get("BRIEF_LLM_MODEL", DEFAULT_MODEL)


# ---------------------------------------------------------------------------
#  Вызов LLM (OpenAI-совместимый /chat/completions через urllib)
# ---------------------------------------------------------------------------

def chat_completion(messages: List[Dict], temperature: float = 0.3,
                    max_tokens: int = 1600, timeout: int = 90) -> str:
    """POST к {base}/chat/completions. Возвращает текст ответа модели."""
    key = get_api_key()
    if not key:
        raise RuntimeError(
            "Нет API-ключа. Задайте DEEPSEEK_API_KEY в окружении "
            "или в файле .env рядом с brief.py")
    url = f"{_base_url()}/chat/completions"
    payload = {
        "model": _model(),
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": False,
    }
    req = Request(
        url, data=json.dumps(payload).encode("utf-8"), method="POST",
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {key}"},
    )
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    with urlopen(req, context=ctx, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    try:
        return resp["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Неожиданный ответ API: {resp}") from exc


# ---------------------------------------------------------------------------
#  Промпт
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = (
    "Ты — старший аналитик мирового рынка меди (LME / COMEX / SHFE) в отделе "
    "закупок промышленного холдинга. Каждое утро ты готовишь краткий брифинг "
    "для закупщиков физической меди.\n"
    "Строгие правила:\n"
    "1. Опирайся ТОЛЬКО на предоставленные заголовки и описания. Не добавляй "
    "фактов извне, не выдумывай цифры, даты и события.\n"
    "2. Если по разделу нет значимых новостей — прямо напиши «без значимых "
    "событий», не придумывай наполнение.\n"
    "3. Пиши по-русски, деловым языком, кратко и по делу, без воды.\n"
    "4. Фокус — что влияет на цену меди: перебои поставок (шахты, забастовки, "
    "аварии), спрос Китая, запасы LME/COMEX/SHFE, курс доллара (DXY), политика "
    "и тарифы, макро (ФРС, инфляция, ставки)."
)

OUTPUT_FORMAT = """Составь брифинг СТРОГО в этом формате (Markdown):

# Брифинг по рынку меди — {date}

## 🎯 Главное за сутки
[Самое важное событие одним абзацем. Почему это важно для цены меди и для закупок.]

## 📰 Что произошло
- **[Тема]**: что случилось и почему важно. 1–2 предложения.
(3–6 пунктов по самым значимым новостям)

## 👀 На что смотреть закупщику
[Ключевые факторы риска и возможности для цены: поставки, Китай, запасы, доллар, политика. Если значимого нет — «без значимых событий».]

## ✅ Рекомендации
[1–3 конкретных действия для отдела закупок. Если действий не требуется — «срочных действий не требуется».]

## 🔗 Источники
[2–3 самых важных заголовка с указанием издания.]"""


def build_messages(news_df: pd.DataFrame, today: Optional[dt.date] = None) -> List[Dict]:
    """Сформировать system + user сообщения из заголовков новостей."""
    today = today or dt.date.today()
    lines = []
    for i, (_, r) in enumerate(news_df.iterrows(), 1):
        try:
            pub_s = pd.Timestamp(r.get("published")).strftime("%Y-%m-%d %H:%M")
        except Exception:
            pub_s = "—"
        title = str(r.get("title", "")).strip()
        summ = str(r.get("summary", "") or "").strip()
        if len(summ) > 220:
            summ = summ[:220] + "…"
        src = str(r.get("source", "")).strip()
        lines.append(f"{i}. [{pub_s} · {src}] {title}" + (f"\n   {summ}" if summ else ""))
    headlines = "\n".join(lines) if lines else "(свежих заголовков нет)"
    user = (
        f"Дата брифинга: {today.isoformat()}.\n\n"
        f"Ниже — заголовки новостей по рынку меди за последние ~48 часов "
        f"(время · издание · заголовок · краткое описание).\n\n"
        f"{OUTPUT_FORMAT.format(date=today.isoformat())}\n\n"
        f"=== ЗАГОЛОВКИ ===\n{headlines}"
    )
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


# ---------------------------------------------------------------------------
#  Сбор новостей
# ---------------------------------------------------------------------------

def _recent_news(news_df: Optional[pd.DataFrame], hours: int = 48,
                 max_items: int = 50) -> pd.DataFrame:
    """Свежие новости за `hours`. Если за окно пусто — берём самые свежие вообще."""
    if news_df is None:
        from news import fetch_all_news
        news_df = fetch_all_news(max_per_query=30, cache_ttl_min=60)
    if news_df is None or news_df.empty:
        return pd.DataFrame()
    df = news_df.copy()
    df["published"] = pd.to_datetime(df["published"], errors="coerce")
    cutoff = pd.Timestamp.now() - pd.Timedelta(hours=hours)
    recent = df[df["published"] >= cutoff]
    if recent.empty:
        recent = df
    return recent.sort_values("published", ascending=False).head(max_items)


# ---------------------------------------------------------------------------
#  Генерация, сохранение, чтение
# ---------------------------------------------------------------------------

def generate_brief(news_df: Optional[pd.DataFrame] = None,
                   today: Optional[dt.date] = None) -> Dict:
    """Сгенерировать брифинг. Возвращает {date, markdown, n_news, model}."""
    today = today or dt.date.today()
    recent = _recent_news(news_df)
    messages = build_messages(recent, today)
    md = chat_completion(messages)
    return {"date": today.isoformat(), "markdown": md,
            "n_news": int(len(recent)), "model": _model()}


def save_brief(result: Dict) -> Path:
    """Сохранить брифинг в data/briefings/YYYY-MM-DD.md и latest.md."""
    BRIEF_DIR.mkdir(parents=True, exist_ok=True)
    day_path = BRIEF_DIR / f"{result['date']}.md"
    day_path.write_text(result["markdown"], encoding="utf-8")
    (BRIEF_DIR / "latest.md").write_text(result["markdown"], encoding="utf-8")
    return day_path


def read_brief(path) -> str:
    return Path(path).read_text(encoding="utf-8")


def latest_brief() -> Optional[Dict]:
    """Последний брифинг для дашборда: {markdown, generated, path}."""
    latest = BRIEF_DIR / "latest.md"
    if not latest.exists():
        files = sorted(BRIEF_DIR.glob("20*.md"), reverse=True) if BRIEF_DIR.exists() else []
        if not files:
            return None
        latest = files[0]
    return {
        "markdown": latest.read_text(encoding="utf-8"),
        "generated": dt.datetime.fromtimestamp(latest.stat().st_mtime),
        "path": str(latest),
    }


def list_briefs(limit: int = 30) -> List[Dict]:
    """Список датированных брифингов (новые сверху)."""
    if not BRIEF_DIR.exists():
        return []
    files = sorted(BRIEF_DIR.glob("20*.md"), reverse=True)[:limit]
    return [{"date": f.stem, "path": str(f)} for f in files]


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    logger.info("Генерирую брифинг по рынку меди…")
    result = generate_brief()
    path = save_brief(result)
    logger.info("Брифинг сохранён: %s (новостей: %d, модель: %s)",
                path, result["n_news"], result["model"])
    print("\n" + result["markdown"])


if __name__ == "__main__":
    main()
