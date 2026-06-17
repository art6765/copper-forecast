"""
backup.py — резервные копии накапливаемых данных (Этап 2).

Зачем: часть данных живёт ТОЛЬКО на VPS (в .gitignore) и невосполнима при потере:
- data/cache_lme_price.csv   — растущая история LME 3M (копится с нуля)
- data/cache_lme_stocks.csv  — запасы LME
- data/cache_cftc_cot.csv    — позиционирование COT
- data/forecast_history.sqlite — журнал прогнозов с фактами
- data/briefings/            — ИИ-брифинги (менее критично)

Делает датированные снапшоты в data/backups/YYYY-MM-DD с ротацией (хранит
последние KEEP_SNAPSHOTS). SQLite копируется через безопасный backup API
(корректно даже если идёт запись), CSV/папки — обычным копированием.

Уровни защиты:
- Этот скрипт защищает от ПОВРЕЖДЕНИЯ или случайного удаления файла (копии
  лежат рядом на том же диске).
- От потери ВСЕГО сервера он НЕ защищает. Для этого периодически копируйте
  data/backups/ вне VPS (scp на свой компьютер или в облако) — см. инструкцию.

Запускать по cron раз в день. Зависимости — только стандартная библиотека.
"""
from __future__ import annotations

import datetime as _dt
import logging
import shutil
import sqlite3
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"

CRITICAL_FILES: List[str] = [
    "cache_lme_price.csv",
    "cache_lme_stocks.csv",
    "cache_cftc_cot.csv",
    "forecast_history.sqlite",
]
CRITICAL_DIRS: List[str] = ["briefings"]

KEEP_SNAPSHOTS = 30  # сколько последних датированных снапшотов хранить


def _copy_sqlite(src: Path, dest: Path) -> None:
    """Горячая копия SQLite через backup API (безопасна при активной записи)."""
    con = sqlite3.connect(str(src))
    try:
        bck = sqlite3.connect(str(dest))
        try:
            with bck:
                con.backup(bck)
        finally:
            bck.close()
    finally:
        con.close()


def make_backup(today: _dt.date | None = None) -> Path:
    """Создать снапшот критичных данных в data/backups/YYYY-MM-DD."""
    today = today or _dt.date.today()
    dest = BACKUP_DIR / today.isoformat()
    dest.mkdir(parents=True, exist_ok=True)

    n = 0
    for fname in CRITICAL_FILES:
        src = DATA_DIR / fname
        if not src.exists():
            continue
        try:
            if fname.endswith(".sqlite") or fname.endswith(".db"):
                _copy_sqlite(src, dest / fname)
            else:
                shutil.copy2(src, dest / fname)
            n += 1
        except Exception as exc:
            logger.warning("Не удалось скопировать %s: %s", fname, exc)

    for dname in CRITICAL_DIRS:
        src = DATA_DIR / dname
        if src.exists() and src.is_dir():
            try:
                shutil.copytree(src, dest / dname, dirs_exist_ok=True)
                n += 1
            except Exception as exc:
                logger.warning("Не удалось скопировать папку %s: %s", dname, exc)

    logger.info("Снапшот создан: %s (%d объектов)", dest, n)
    return dest


def rotate(keep: int = KEEP_SNAPSHOTS) -> int:
    """Удалить снапшоты сверх `keep` последних (по дате). Возвращает число удалённых."""
    if not BACKUP_DIR.exists():
        return 0
    snaps = sorted([p for p in BACKUP_DIR.iterdir() if p.is_dir()], reverse=True)
    removed = 0
    for old in snaps[keep:]:
        shutil.rmtree(old, ignore_errors=True)
        removed += 1
    if removed:
        logger.info("Удалено старых снапшотов: %d", removed)
    return removed


def main():
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(message)s")
    dest = make_backup()
    removed = rotate()
    objs = len(list(dest.glob("*"))) if dest.exists() else 0
    print(f"Бэкап готов: {dest} — объектов: {objs}, удалено старых: {removed}")


if __name__ == "__main__":
    main()
