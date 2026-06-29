"""
history_db.py — журнал РЕАЛЬНЫХ прогнозов в SQLite + сверка с фактом.

Чем отличается от backtest.py:
  - backtest.py — ретроспективная walk-forward валидация: «что бы предсказала
    модель, если бы стояла в прошлом». Запускается по требованию, ничего не
    хранит между запусками.
  - history_db.py — ЖУРНАЛ настоящих прогнозов, которые система выдала в каждый
    реальный запуск. Когда наступает целевая дата горизонта и становится известна
    фактическая цена, прогноз «разрешается» (resolve): считаются попадание по
    направлению (рост/падение угадан), попадание факта в коридор [p10, p90] и
    ошибки прогноза (MAE / MAPE / bias). Это даёт честную картину реальной
    точности по каждому горизонту (3д / 10д / 1м / 3м / 6м) и каждой модели.

Сверка горизонта: горизонт H измеряется в ТОРГОВЫХ днях (как при обучении —
make_target сдвигает на H баров). Поэтому факт берётся позиционным сдвигом по
ряду цен: позиция базовой даты + H. Это согласовано с models.actuals_after_point.

Хранилище: data/forecast_history.sqlite (только стандартная библиотека sqlite3,
никаких новых зависимостей). На VPS файл персистентен — журнал копится между
запусками. На Streamlit Community Cloud файловая система эфемерна (сбрасывается
при перезапуске/редеплое), поэтому для накопления реального журнала нужен VPS.
"""
from __future__ import annotations

import datetime as _dt
import logging
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Путь к БД. data/ уже существует в проекте (там же кэши котировок).
DB_PATH = Path(__file__).resolve().parent / "data" / "forecast_history.sqlite"

# Горизонты — синхронизированы с models.HORIZONS. Дублируем как лёгкий фолбэк,
# чтобы модуль работал даже без импорта тяжёлого models.
_HORIZONS_FALLBACK: List[Dict] = [
    {"key": "h_today",    "label": "Сегодня",   "days": 1},
    {"key": "h_tomorrow", "label": "Завтра",    "days": 2},
    {"key": "h_3d",  "label": "3 дня",     "days": 3},
    {"key": "h_10d", "label": "10 дней",   "days": 10},
    {"key": "h_1m",  "label": "1 месяц",   "days": 21},
    {"key": "h_3m",  "label": "3 месяца",  "days": 63},
    {"key": "h_6m",  "label": "6 месяцев", "days": 126},
]


def _horizons() -> List[Dict]:
    try:
        from models import HORIZONS
        return HORIZONS
    except Exception:
        return _HORIZONS_FALLBACK


def _key_by_days() -> Dict[int, str]:
    return {h["days"]: h["key"] for h in _horizons()}


def _label_by_days() -> Dict[int, str]:
    return {h["days"]: h["label"] for h in _horizons()}


# Колонки таблицы (порядок важен для INSERT)
_COLUMNS = [
    "as_of_date", "created_at", "model", "horizon_key", "horizon_label",
    "horizon_days", "target_date", "p0", "point", "median",
    "p10", "p25", "p75", "p90", "change_pct", "prob_up", "sigma_t", "source",
    "resolved", "resolved_at", "actual_date", "actual_price",
    "abs_error", "pct_error", "signed_error", "direction_correct", "in_interval_80",
    "market",
]


# ---------------------------------------------------------------------------
#  Соединение и схема
# ---------------------------------------------------------------------------

def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    """Открыть (и при необходимости создать) БД журнала. Схема создаётся сразу."""
    p = Path(path) if path is not None else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p))
    init_db(conn)
    return conn


_SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS forecast_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    as_of_date      TEXT NOT NULL,
    created_at      TEXT,
    model           TEXT NOT NULL,
    horizon_key     TEXT,
    horizon_label   TEXT,
    horizon_days    INTEGER NOT NULL,
    target_date     TEXT,
    p0              REAL,
    point           REAL,
    median          REAL,
    p10             REAL,
    p25             REAL,
    p75             REAL,
    p90             REAL,
    change_pct      REAL,
    prob_up         REAL,
    sigma_t         REAL,
    source          TEXT DEFAULT 'live',
    resolved        INTEGER DEFAULT 0,
    resolved_at     TEXT,
    actual_date     TEXT,
    actual_price    REAL,
    abs_error       REAL,
    pct_error       REAL,
    signed_error    REAL,
    direction_correct INTEGER,
    in_interval_80  INTEGER,
    market          TEXT DEFAULT 'COMEX',   -- COMEX | LME
    UNIQUE(as_of_date, model, horizon_days, source, market)
)
"""


def _migrate_add_market(conn: sqlite3.Connection) -> None:
    """Миграция старой схемы (без market) → новая. Старые записи помечаются COMEX,
    UNIQUE расширяется на market. Данные не теряются."""
    conn.execute("ALTER TABLE forecast_log RENAME TO _forecast_log_old")
    conn.execute(_SCHEMA_SQL)
    old_cols = [r[1] for r in conn.execute(
        "PRAGMA table_info(_forecast_log_old)").fetchall()]
    common = [c for c in old_cols if c != "id"]
    conn.execute(
        f"INSERT INTO forecast_log ({', '.join(common)}, market) "
        f"SELECT {', '.join(common)}, 'COMEX' FROM _forecast_log_old"
    )
    conn.execute("DROP TABLE _forecast_log_old")
    logger.info("Журнал мигрирован: добавлена колонка market (старые записи → COMEX)")


def init_db(conn: sqlite3.Connection) -> None:
    """Создать таблицу/индексы; при необходимости мигрировать старую схему."""
    exists = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='forecast_log'"
    ).fetchone()
    if exists:
        cols = [r[1] for r in conn.execute(
            "PRAGMA table_info(forecast_log)").fetchall()]
        if "market" not in cols:
            _migrate_add_market(conn)
    else:
        conn.execute(_SCHEMA_SQL)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fl_resolved ON forecast_log(resolved)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fl_model_h ON forecast_log(model, horizon_days)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fl_asof ON forecast_log(as_of_date)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_fl_market ON forecast_log(market)")
    conn.commit()


# ---------------------------------------------------------------------------
#  Вспомогательные
# ---------------------------------------------------------------------------

def _f(x) -> Optional[float]:
    """None-safe приведение к float (np.nan → None)."""
    if x is None:
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(v) else v


def _i(x) -> Optional[int]:
    if x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _pick(r, *names):
    """Первое доступное значение среди возможных имён колонок.
    Позволяет принимать и COMEX-таблицу (USD/lb), и LME-таблицу (USD/т)."""
    for n in names:
        if n in r and r.get(n) is not None:
            return r.get(n)
    return None


def _resolution_metrics(p0: float, point: float, p10: float, p90: float,
                        actual: float) -> Dict:
    """Метрики попадания прогноза в факт."""
    abs_err = abs(actual - point)
    pct_err = (abs_err / actual * 100) if actual else None
    signed = point - actual
    # Направление: сравниваем знак (point vs p0) и (actual vs p0)
    dir_ok = int((point > p0) == (actual > p0))
    in80 = int((p10 is not None and p90 is not None) and (p10 <= actual <= p90))
    return {
        "abs_error": abs_err,
        "pct_error": pct_err,
        "signed_error": signed,
        "direction_correct": dir_ok,
        "in_interval_80": in80,
    }


# ---------------------------------------------------------------------------
#  Запись прогнозов
# ---------------------------------------------------------------------------

def log_forecast(df_fc: pd.DataFrame, as_of_date, source: str = "live",
                 market: str = "COMEX",
                 conn: Optional[sqlite3.Connection] = None) -> int:
    """Записать прогнозы из таблицы forecasts_to_dataframe в журнал.

    Идемпотентно по (дата, модель, горизонт, source, market) — INSERT OR IGNORE.
    market: 'COMEX' (цены USD/lb) или 'LME' (цены USD/т). Имена ценовых колонок
    подбираются гибко (_pick), поэтому подходит и COMEX-, и LME-таблица.
    Возвращает число фактически добавленных строк.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        as_of = pd.Timestamp(as_of_date)
        as_of_s = as_of.strftime("%Y-%m-%d")
        created = _now_iso()
        bday = pd.tseries.offsets.BusinessDay()

        rows = []
        for _, r in df_fc.iterrows():
            H = _i(r.get("Дней"))
            if H is None:
                continue
            target = (as_of + H * bday).strftime("%Y-%m-%d")
            rows.append((
                as_of_s, created, str(r.get("Модель")),
                _key_by_days().get(H, ""), str(r.get("Горизонт")), H, target,
                _f(_pick(r, "P0, USD/lb", "P0, USD/т")),
                _f(_pick(r, "Точечный", "Точечный, USD/т")),
                _f(_pick(r, "Медиана", "Медиана, USD/т")),
                _f(_pick(r, "p10", "p10, USD/т")), _f(_pick(r, "p25", "p25, USD/т")),
                _f(_pick(r, "p75", "p75, USD/т")), _f(_pick(r, "p90", "p90, USD/т")),
                _f(r.get("Δ, %")), _f(r.get("P(↑), %")), _f(r.get("σ_T")), source,
                0, None, None, None, None, None, None, None, None,
                market,
            ))
        before = _total(conn)
        conn.executemany(
            f"INSERT OR IGNORE INTO forecast_log ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_COLUMNS))})",
            rows,
        )
        conn.commit()
        return _total(conn) - before
    finally:
        if own:
            conn.close()


def log_walkforward(predictions: Dict[str, Dict[int, pd.DataFrame]],
                    conn: Optional[sqlite3.Connection] = None) -> int:
    """Наполнить журнал ретроспективными прогнозами из backtest.walk_forward.

    predictions — структура bt["predictions"]: {model: {H: DataFrame}}, где
    DataFrame имеет индекс=дата прогноза и колонки p0, actual, point, p10, p90.
    Такие строки сразу помечаются resolved=1 (факт уже известен), source='backfill'.
    Возвращает число добавленных строк.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        created = _now_iso()
        key_by = _key_by_days()
        label_by = _label_by_days()
        bday = pd.tseries.offsets.BusinessDay()
        rows = []
        for model, by_h in (predictions or {}).items():
            for H, dfp in by_h.items():
                if dfp is None or dfp.empty:
                    continue
                Hi = int(H)
                for date, r in dfp.iterrows():
                    p0 = _f(r.get("p0"))
                    actual = _f(r.get("actual"))
                    point = _f(r.get("point"))
                    p10 = _f(r.get("p10"))
                    p90 = _f(r.get("p90"))
                    if p0 is None or actual is None or point is None:
                        continue
                    as_of = pd.Timestamp(date)
                    m = _resolution_metrics(p0, point, p10, p90, actual)
                    change_pct = (point - p0) / p0 * 100 if p0 else None
                    rows.append((
                        as_of.strftime("%Y-%m-%d"), created, str(model),
                        key_by.get(Hi, ""), label_by.get(Hi, str(Hi)), Hi,
                        (as_of + Hi * bday).strftime("%Y-%m-%d"),
                        p0, point, None, p10, None, None, p90,
                        change_pct, None, None, "backfill",
                        1, created, (as_of + Hi * bday).strftime("%Y-%m-%d"), actual,
                        m["abs_error"], m["pct_error"], m["signed_error"],
                        m["direction_correct"], m["in_interval_80"],
                        "COMEX",
                    ))
        before = _total(conn)
        conn.executemany(
            f"INSERT OR IGNORE INTO forecast_log ({', '.join(_COLUMNS)}) "
            f"VALUES ({', '.join('?' * len(_COLUMNS))})",
            rows,
        )
        conn.commit()
        return _total(conn) - before
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
#  Сверка с фактом
# ---------------------------------------------------------------------------

def resolve_due(price_series: pd.Series, market: str = "COMEX",
                conn: Optional[sqlite3.Connection] = None) -> int:
    """Разрешить прогнозы данного рынка, для которых наступила целевая дата.

    price_series — актуальный ряд цен соответствующего рынка с DatetimeIndex
    (COMEX → raw["copper"] USD/lb; LME → raw["lme_3m"] USD/т).
    Факт берётся позиционным сдвигом: позиция базовой даты + H торговых дней.
    Возвращает число разрешённых на этом проходе прогнозов.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        ps = price_series.dropna()
        if ps.empty:
            return 0
        idx = ps.index
        cur = conn.execute(
            "SELECT id, as_of_date, horizon_days, p0, point, p10, p90 "
            "FROM forecast_log WHERE resolved = 0 AND market = ?",
            (market,),
        )
        pending = cur.fetchall()
        resolved_at = _now_iso()
        n = 0
        for (rid, as_of_s, H, p0, point, p10, p90) in pending:
            as_of = pd.Timestamp(as_of_s)
            # Позиция базовой даты в ряду (точная либо ближайший торговый день <= as_of)
            pos = int(idx.searchsorted(as_of, side="right")) - 1
            if pos < 0:
                continue
            target_pos = pos + int(H)
            if target_pos >= len(ps):
                continue  # факт ещё не наступил
            actual_date = idx[target_pos]
            actual = float(ps.iloc[target_pos])
            if p0 is None or point is None:
                continue
            m = _resolution_metrics(float(p0), float(point), _f(p10), _f(p90), actual)
            conn.execute(
                "UPDATE forecast_log SET resolved=1, resolved_at=?, actual_date=?, "
                "actual_price=?, abs_error=?, pct_error=?, signed_error=?, "
                "direction_correct=?, in_interval_80=? WHERE id=?",
                (resolved_at, actual_date.strftime("%Y-%m-%d"), actual,
                 m["abs_error"], m["pct_error"], m["signed_error"],
                 m["direction_correct"], m["in_interval_80"], rid),
            )
            n += 1
        conn.commit()
        return n
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
#  Аналитика и выгрузка
# ---------------------------------------------------------------------------

def accuracy_summary(conn: Optional[sqlite3.Connection] = None,
                     model: Optional[str] = None,
                     source: Optional[str] = None,
                     market: Optional[str] = None) -> pd.DataFrame:
    """Сводка точности по (модель × горизонт) на разрешённых прогнозах.

    market: 'COMEX' / 'LME' / None (все). Колонки: model, horizon_days,
    horizon_label, n, hit_rate (%), coverage80 (%), mae, mape (%), bias.
    """
    own = conn is None
    if own:
        conn = connect()
    try:
        where = ["resolved = 1"]
        params: List = []
        if model:
            where.append("model = ?")
            params.append(model)
        if source:
            where.append("source = ?")
            params.append(source)
        if market:
            where.append("market = ?")
            params.append(market)
        q = f"SELECT * FROM forecast_log WHERE {' AND '.join(where)}"
        df = pd.read_sql_query(q, conn, params=params)
        if df.empty:
            return pd.DataFrame(columns=[
                "model", "horizon_days", "horizon_label", "n",
                "hit_rate", "coverage80", "mae", "mape", "bias",
            ])
        g = (df.groupby(["model", "horizon_days", "horizon_label"], dropna=False)
               .agg(n=("id", "size"),
                    hit_rate=("direction_correct", "mean"),
                    coverage80=("in_interval_80", "mean"),
                    mae=("abs_error", "mean"),
                    mape=("pct_error", "mean"),
                    bias=("signed_error", "mean"))
               .reset_index())
        g["hit_rate"] = g["hit_rate"] * 100
        g["coverage80"] = g["coverage80"] * 100
        return g.sort_values(["model", "horizon_days"]).reset_index(drop=True)
    finally:
        if own:
            conn.close()


def load_log(conn: Optional[sqlite3.Connection] = None,
             resolved_only: bool = False,
             model: Optional[str] = None,
             horizon_days: Optional[int] = None,
             source: Optional[str] = None,
             market: Optional[str] = None,
             limit: Optional[int] = None) -> pd.DataFrame:
    """Выгрузить журнал в DataFrame (для таблиц/графиков в UI)."""
    own = conn is None
    if own:
        conn = connect()
    try:
        where: List[str] = []
        params: List = []
        if resolved_only:
            where.append("resolved = 1")
        if model:
            where.append("model = ?")
            params.append(model)
        if horizon_days is not None:
            where.append("horizon_days = ?")
            params.append(int(horizon_days))
        if source:
            where.append("source = ?")
            params.append(source)
        if market:
            where.append("market = ?")
            params.append(market)
        q = "SELECT * FROM forecast_log"
        if where:
            q += " WHERE " + " AND ".join(where)
        q += " ORDER BY as_of_date DESC, horizon_days ASC"
        if limit:
            q += f" LIMIT {int(limit)}"
        return pd.read_sql_query(q, conn, params=params)
    finally:
        if own:
            conn.close()


def _total(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM forecast_log").fetchone()[0])


def get_stats(conn: Optional[sqlite3.Connection] = None) -> Dict:
    """Краткая статистика журнала для шапки вкладки."""
    own = conn is None
    if own:
        conn = connect()
    try:
        total = _total(conn)
        resolved = int(conn.execute(
            "SELECT COUNT(*) FROM forecast_log WHERE resolved=1").fetchone()[0])
        live = int(conn.execute(
            "SELECT COUNT(*) FROM forecast_log WHERE source='live'").fetchone()[0])
        backfill = int(conn.execute(
            "SELECT COUNT(*) FROM forecast_log WHERE source='backfill'").fetchone()[0])
        rng = conn.execute(
            "SELECT MIN(as_of_date), MAX(as_of_date) FROM forecast_log").fetchone()
        return {
            "total": total,
            "resolved": resolved,
            "pending": total - resolved,
            "live": live,
            "backfill": backfill,
            "first_date": rng[0],
            "last_date": rng[1],
        }
    finally:
        if own:
            conn.close()


def clear(conn: Optional[sqlite3.Connection] = None,
          source: Optional[str] = None) -> int:
    """Удалить записи (опционально только одного source). Возвращает число удалённых."""
    own = conn is None
    if own:
        conn = connect()
    try:
        if source:
            cur = conn.execute("DELETE FROM forecast_log WHERE source=?", (source,))
        else:
            cur = conn.execute("DELETE FROM forecast_log")
        conn.commit()
        return cur.rowcount
    finally:
        if own:
            conn.close()


# ---------------------------------------------------------------------------
#  Высокоуровневая обёртка для приложения
# ---------------------------------------------------------------------------

def record_live_forecast(df_fc: pd.DataFrame, as_of_date, price_series: pd.Series,
                         path: Optional[Path] = None,
                         lme_df: Optional[pd.DataFrame] = None,
                         lme_series: Optional[pd.Series] = None) -> Dict[str, int]:
    """Один вызов из app.py: записать текущий прогноз(ы) и разрешить наступившие.

    COMEX-прогноз (df_fc) пишется с market='COMEX' и резолвится по price_series
    (raw["copper"], USD/lb). Если переданы lme_df (forecast_lme_direct) и
    lme_series (raw["lme_3m"], USD/т) — дополнительно пишется LME-прогноз
    (market='LME') с резолвом по lme_series. Запись идемпотентна.
    """
    conn = connect(path)
    try:
        logged = log_forecast(df_fc, as_of_date, source="live",
                              market="COMEX", conn=conn)
        resolved = resolve_due(price_series, market="COMEX", conn=conn)
        if lme_df is not None and not lme_df.empty and lme_series is not None:
            ls = lme_series.dropna()
            if len(ls):
                logged += log_forecast(lme_df, ls.index[-1], source="live",
                                       market="LME", conn=conn)
                resolved += resolve_due(ls, market="LME", conn=conn)
        return {"logged": logged, "resolved": resolved}
    finally:
        conn.close()


if __name__ == "__main__":
    # Мини-демо/проверка на синтетике
    logging.basicConfig(level=logging.INFO)
    import tempfile

    tmp = Path(tempfile.mkdtemp()) / "demo.sqlite"
    conn = connect(tmp)

    df_demo = pd.DataFrame([
        {"Горизонт": "3 дня", "Дней": 3, "Модель": "Ensemble", "P0, USD/lb": 4.0,
         "Точечный": 4.1, "Медиана": 4.1, "p10": 3.9, "p25": 4.0, "p75": 4.2,
         "p90": 4.3, "Δ, %": 2.5, "P(↑), %": 60.0, "σ_T": 0.05},
    ])
    print("logged:", log_forecast(df_demo, "2026-01-05", conn=conn))

    dates = pd.bdate_range("2026-01-05", periods=10)
    prices = pd.Series([4.0, 4.02, 4.05, 4.12, 4.08, 4.1, 4.15, 4.2, 4.18, 4.25],
                       index=dates)
    print("resolved:", resolve_due(prices, conn=conn))
    print(accuracy_summary(conn=conn).to_string(index=False))
    conn.close()
