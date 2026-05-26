"""
news.py — парсер свежих новостей про медь из Google News RSS.

Почему Google News:
- Бесплатно, без ключа.
- Агрегирует Reuters, WSJ, Bloomberg, MINING.COM, Kitco и др.
- Стабильный URL и формат.
- 100 заголовков на запрос, обновление каждые 15 минут.

Альтернативы:
- Reuters/MINING.COM прямые RSS — блокируют наш User-Agent (403 Cloudflare).
- ACLED, NewsAPI — требуют ключи и/или академический доступ.

Каждая новость:
- title, link, published, source (издание), summary
- tags — вычисленные из заголовка (supply_shock / policy / macro / china / …)

Кэш: data/cache_news.csv с TTL 1 час.
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import quote

import pandas as pd

from extra_sources import _get

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(exist_ok=True)


# Готовые запросы для разных аспектов рынка меди
DEFAULT_QUERIES = {
    "general":   "copper price",
    "supply":    "copper mine strike OR closure OR Cobre OR Escondida",
    "policy":    "copper tariff OR sanction OR LME",
    "smelter":   "copper smelter TC RC China",
    "china":     "China copper demand PMI Caixin",
    "structural": "copper EV electric vehicle demand grid",
}


# Эвристика тегов по ключевым словам в заголовке
TAG_RULES = [
    ("supply_shock", [r"\bmine\b", r"strike", r"closure", r"shutdown", r"force majeure",
                       r"escondida", r"cobre", r"chuquicamata", r"collahuasi",
                       r"grasberg", r"oyu tolgoi", r"kamoa",
                       r"earthquake", r"disrupt", r"halt", r"suspend",
                       r"withdrawal", r"withdraw \d+", r"pulls? \d+"]),
    ("policy",       [r"tariff", r"sanction", r"export ban", r"trump", r"biden",
                       r"executive order"]),
    ("smelter",      [r"smelter", r"refinery", r"\btc/?rc\b", r"treatment charge"]),
    ("macro",        [r"\bfed\b", r"federal reserve", r"interest rate", r"fomc",
                       r"\bcpi\b", r"\bppi\b", r"inflation"]),
    ("china",        [r"china", r"chinese", r"caixin", r"\bpmi\b", r"\bcny\b",
                       r"yuan", r"evergrande", r"country garden", r"shanghai"]),
    ("price_move",   [r"record high", r"new high", r"surges?", r"plunges?",
                       r"crashes?", r"rallies?", r"slumps?", r"tumbles?"]),
    ("structural",   [r"electric vehicle", r"\bev\b", r"battery", r"data ?center",
                       r"renewable", r"grid"]),
    ("inventory",    [r"stocks?", r"inventory", r"warehouse", r"\blme stocks?\b"]),
]


@dataclass
class NewsItem:
    title: str
    link: str
    published: dt.datetime
    source: str          # издание
    summary: str
    query: str           # из какого запроса получено
    tags: List[str]

    def to_dict(self) -> Dict:
        d = asdict(self)
        d["published"] = self.published.isoformat()
        d["tags"] = ",".join(self.tags)
        return d


def _parse_pubdate(text: Optional[str]) -> dt.datetime:
    if not text:
        return dt.datetime.now()
    # Формат RFC 822: "Mon, 25 May 2026 14:30:00 GMT"
    fmts = [
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%SZ",
    ]
    for f in fmts:
        try:
            return dt.datetime.strptime(text.strip(), f).replace(tzinfo=None)
        except Exception:
            continue
    try:
        return pd.to_datetime(text, errors="coerce").to_pydatetime()
    except Exception:
        return dt.datetime.now()


def _classify(title: str, summary: str) -> List[str]:
    """Эвристическая разметка тегами по словарю."""
    text = (title + " " + summary).lower()
    tags = []
    for tag, patterns in TAG_RULES:
        for pat in patterns:
            if re.search(pat, text, re.IGNORECASE):
                tags.append(tag)
                break
    return tags


def _strip_source(title: str) -> tuple[str, str]:
    """Google News заголовок вида 'Copper hits high - Reuters' → (заголовок, издание)."""
    if " - " in title:
        head, src = title.rsplit(" - ", 1)
        return head.strip(), src.strip()
    return title.strip(), "Google News"


def fetch_news_query(query: str, max_items: int = 50) -> List[NewsItem]:
    """Скачать новости по одному запросу из Google News RSS."""
    url = (
        f"https://news.google.com/rss/search?"
        f"q={quote(query)}&hl=en-US&gl=US&ceid=US:en"
    )
    data = _get(url, timeout=15)
    text = data.decode("utf-8", errors="replace")
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        logger.warning("RSS parse error for query=%r: %s", query, exc)
        return []

    items: List[NewsItem] = []
    for item in root.iter("item"):
        title_raw = (item.findtext("title") or "").strip()
        link = (item.findtext("link") or "").strip()
        pub  = _parse_pubdate(item.findtext("pubDate"))
        descr = (item.findtext("description") or "").strip()
        # Чистим HTML-теги в description (там Google News вставляет ссылки списком)
        summary = re.sub(r"<[^>]+>", " ", descr)
        summary = re.sub(r"\s+", " ", summary).strip()
        if len(summary) > 400:
            summary = summary[:400] + "…"

        title_clean, source = _strip_source(title_raw)
        items.append(NewsItem(
            title=title_clean,
            link=link,
            published=pub,
            source=source,
            summary=summary,
            query=query,
            tags=_classify(title_clean, summary),
        ))
        if len(items) >= max_items:
            break
    return items


def fetch_all_news(queries: Optional[Dict[str, str]] = None,
                   max_per_query: int = 30,
                   cache_ttl_min: int = 60) -> pd.DataFrame:
    """
    Собирает новости по всем заданным запросам и агрегирует в DataFrame.
    Кэш — data/cache_news.csv, обновляется каждые `cache_ttl_min` минут.

    Колонки: title, link, published, source, summary, query, tags.
    """
    cache = DATA_DIR / "cache_news.csv"
    if cache.exists():
        try:
            df_cached = pd.read_csv(cache)
            df_cached["published"] = pd.to_datetime(df_cached["published"], errors="coerce")
            mtime = dt.datetime.fromtimestamp(cache.stat().st_mtime)
            if (dt.datetime.now() - mtime).total_seconds() < cache_ttl_min * 60:
                return df_cached
        except Exception:
            pass

    queries = queries or DEFAULT_QUERIES
    all_rows = []
    for tag, q in queries.items():
        try:
            items = fetch_news_query(q, max_per_query)
            for it in items:
                row = it.to_dict()
                row["query_tag"] = tag
                all_rows.append(row)
        except Exception as exc:
            logger.warning("Query %r failed: %s", q, exc)

    if not all_rows:
        return pd.DataFrame()

    df = pd.DataFrame(all_rows)
    df["published"] = pd.to_datetime(df["published"], errors="coerce")

    # Дедуп: одинаковые link (Google News иногда возвращает одну статью в разных запросах)
    df = df.sort_values("published", ascending=False)
    df = df.drop_duplicates(subset=["link"]).reset_index(drop=True)

    df.to_csv(cache, index=False)
    logger.info("News: %d уникальных статей (после dedup)", len(df))
    return df


def news_between(df: pd.DataFrame, start: dt.date, end: dt.date) -> pd.DataFrame:
    """Фильтр новостей по диапазону дат."""
    if df.empty:
        return df
    mask = (df["published"].dt.date >= start) & (df["published"].dt.date <= end)
    return df.loc[mask].sort_values("published", ascending=False)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    df = fetch_all_news(max_per_query=20)
    print(f"\nВсего статей: {len(df)}")
    print(df.head(10)[["published", "source", "title", "tags"]].to_string(index=False))
