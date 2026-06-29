"""
alerts.py — уведомления закупщику в Telegram при смене сигнала.

Шлёт сообщение, когда меняется вердикт по ключевому горизонту или цена резко
двигается — чтобы не сидеть в дашборде. Работает, ТОЛЬКО если заданы
TELEGRAM_BOT_TOKEN и TELEGRAM_CHAT_ID (переменные окружения или .env рядом).
Иначе тихо пропускает (как неподключённые платные источники).

Состояние прошлой проверки — в data/alert_state.json (чтобы слать только при
изменении, а не каждый запуск). Вызывается из forecast.py (ежедневный cron).
Новых зависимостей нет — только стандартная библиотека (urllib).

Как подключить:
  1. В Telegram написать @BotFather → /newbot → получить TELEGRAM_BOT_TOKEN.
  2. Написать своему боту любое сообщение, затем открыть
     https://api.telegram.org/bot<TOKEN>/getUpdates и найти chat.id — это
     TELEGRAM_CHAT_ID.
  3. Вписать обе строки в файл .env рядом с проектом.
"""
from __future__ import annotations

import json
import logging
import os
import ssl
from pathlib import Path
from typing import Dict, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
STATE_PATH = BASE_DIR / "data" / "alert_state.json"

# Порог резкого движения цены между проверками, %
PRICE_MOVE_ALERT = 3.0


def _cfg(key: str) -> Optional[str]:
    """Значение из окружения или из .env рядом с проектом."""
    v = os.environ.get(key)
    if v:
        return v.strip()
    try:
        import brief
        val = (brief._read_env_file().get(key) or "").strip()
        return val or None
    except Exception:
        return None


def is_configured() -> bool:
    """Заданы ли токен бота и chat_id."""
    return bool(_cfg("TELEGRAM_BOT_TOKEN") and _cfg("TELEGRAM_CHAT_ID"))


def send_telegram(text: str) -> bool:
    """Отправить сообщение в Telegram. False, если не настроено или ошибка."""
    token = _cfg("TELEGRAM_BOT_TOKEN")
    chat = _cfg("TELEGRAM_CHAT_ID")
    if not (token and chat):
        logger.info("Telegram не настроен — алерт пропущен")
        return False
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urlencode({"chat_id": chat, "text": text,
                      "parse_mode": "HTML"}).encode("utf-8")
    ctx = ssl.create_default_context()
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    try:
        req = Request(url, data=data, method="POST")
        with urlopen(req, context=ctx, timeout=20) as r:
            json.loads(r.read())
        return True
    except Exception as exc:
        logger.warning("Не удалось отправить Telegram-алерт: %s", exc)
        return False


def _load_state() -> Dict:
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_state(state: Dict) -> None:
    try:
        STATE_PATH.parent.mkdir(exist_ok=True)
        STATE_PATH.write_text(json.dumps(state, ensure_ascii=False),
                              encoding="utf-8")
    except Exception as exc:
        logger.warning("Не удалось сохранить состояние алертов: %s", exc)


def check_and_alert(verdict_key: str, verdict_label: str, horizon_label: str,
                    price_usd_t: float, change_pct: float,
                    immediate_pct: Optional[int] = None) -> bool:
    """Сравнить с прошлой проверкой и отправить алерт при смене вердикта или
    резком (>PRICE_MOVE_ALERT%) движении цены. True, если алерт отправлен."""
    if not is_configured():
        return False
    state = _load_state()
    prev_verdict = state.get("verdict_key")
    prev_price = state.get("price_usd_t")

    triggers = []
    if prev_verdict and prev_verdict != verdict_key:
        triggers.append(f"Сменился сигнал: <b>{verdict_label}</b> "
                        f"(было: {state.get('verdict_label', '—')})")
    if prev_price:
        move = (price_usd_t / prev_price - 1) * 100
        if abs(move) >= PRICE_MOVE_ALERT:
            triggers.append(f"Цена сдвинулась на {move:+.1f}% с прошлой проверки")

    sent = False
    if triggers:
        lines = ["🟫 <b>CopperCast — сигнал по меди</b>", *triggers,
                 f"Срок: {horizon_label} · прогноз {price_usd_t:,.0f} USD/т "
                 f"({change_pct:+.1f}%)"]
        if immediate_pct is not None:
            lines.append(f"Рекомендация: взять ~{immediate_pct}% сейчас")
        sent = send_telegram("\n".join(lines))

    state.update({"verdict_key": verdict_key, "verdict_label": verdict_label,
                  "price_usd_t": price_usd_t, "horizon_label": horizon_label})
    _save_state(state)
    return sent


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Telegram настроен:", is_configured())
    if is_configured():
        ok = send_telegram("🟫 CopperCast: тестовое сообщение. Алерты подключены.")
        print("Тестовое сообщение отправлено:", ok)
