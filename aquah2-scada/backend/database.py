"""
AquaH2 AI-SCADA — Time-Series Database (SQLite)
Stores sensor history, alarm log, decisions, events.
In production: replace with InfluxDB, TimescaleDB, or PostgreSQL.

Kraefegg M.O. · Developer: Railson
"""

import sqlite3
import json
import time
from typing import List, Dict, Any, Optional
from contextlib import contextmanager
from config import DB_PATH, HISTORY_RETENTION_HOURS


# ── Schema ────────────────────────────────────────────────────────────

SCHEMA = """
CREATE TABLE IF NOT EXISTS sensor_history (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    tag       TEXT    NOT NULL,
    value     REAL    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sh_tag_ts ON sensor_history (tag, ts);

CREATE TABLE IF NOT EXISTS events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    level     TEXT    NOT NULL,   -- info | warn | alarm | trip | ai
    code      TEXT    NOT NULL,
    message   TEXT    NOT NULL,
    detail    TEXT    DEFAULT ''
);
CREATE INDEX IF NOT EXISTS idx_ev_ts ON events (ts);

CREATE TABLE IF NOT EXISTS setpoint_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    tag       TEXT    NOT NULL,
    old_value REAL,
    new_value REAL    NOT NULL,
    source    TEXT    DEFAULT 'operator'  -- 'operator' | 'ai'
);

CREATE TABLE IF NOT EXISTS chat_log (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL    NOT NULL,
    role      TEXT    NOT NULL,
    content   TEXT    NOT NULL,
    session   TEXT    DEFAULT 'default'
);
"""

# Key metrics to persist every tick
SENSOR_TAGS = [
    "stack_a_temp", "stack_b_temp",
    "stack_a_pressure", "stack_b_pressure",
    "stack_a_h2", "stack_b_h2",
    "stack_a_efficiency", "stack_b_efficiency",
    "solar_mw", "wind_mw", "total_mw",
    "bess_soc", "bess_power_kw",
    "swro_pressure", "swro_salinity", "swro_flow",
    "h2_tank_level", "nh3_rate",
]


class Database:
    def __init__(self, path: str = DB_PATH):
        self.path = path
        self._init_db()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path, timeout=10)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_db(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ── Write ──────────────────────────────────────────────────────────

    def record_sensors(self, state_dict: Dict[str, Any]):
        """Extract key readings from plant state dict and persist."""
        ts = state_dict.get("timestamp", time.time())
        rows = []

        def add(tag, val):
            if val is not None and isinstance(val, (int, float)):
                rows.append((ts, tag, float(val)))

        sa = state_dict.get("stack_a", {})
        sb = state_dict.get("stack_b", {})
        en = state_dict.get("energy", {})
        bs = state_dict.get("bess", {})
        sw = state_dict.get("swro", {})
        h2 = state_dict.get("h2_storage", {})
        nh = state_dict.get("nh3", {})

        add("stack_a_temp",       sa.get("temp_cell"))
        add("stack_b_temp",       sb.get("temp_cell"))
        add("stack_a_pressure",   sa.get("pressure_h2"))
        add("stack_b_pressure",   sb.get("pressure_h2"))
        add("stack_a_h2",         sa.get("h2_production"))
        add("stack_b_h2",         sb.get("h2_production"))
        add("stack_a_efficiency", sa.get("efficiency_lhv"))
        add("stack_b_efficiency", sb.get("efficiency_lhv"))
        add("solar_mw",           en.get("solar_mw"))
        add("wind_mw",            en.get("wind_mw"))
        add("total_mw",           en.get("total_mw"))
        add("bess_soc",           bs.get("soc"))
        add("bess_power_kw",      bs.get("power_kw"))
        add("swro_pressure",      sw.get("feed_pressure"))
        add("swro_salinity",      sw.get("product_salinity"))
        add("swro_flow",          sw.get("product_flow"))
        add("h2_tank_level",      h2.get("tank_level_pct"))
        add("nh3_rate",           nh.get("production_kgh"))

        with self._conn() as conn:
            conn.executemany(
                "INSERT INTO sensor_history (ts, tag, value) VALUES (?, ?, ?)", rows)

    def record_event(self, level: str, code: str, message: str, detail: str = ""):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO events (ts, level, code, message, detail) VALUES (?, ?, ?, ?, ?)",
                (time.time(), level, code, message, detail))

    def record_setpoint(self, tag: str, old_val: float, new_val: float, source: str = "operator"):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO setpoint_log (ts, tag, old_value, new_value, source) VALUES (?, ?, ?, ?, ?)",
                (time.time(), tag, old_val, new_val, source))

    def record_chat(self, role: str, content: str, session: str = "default"):
        with self._conn() as conn:
            conn.execute(
                "INSERT INTO chat_log (ts, role, content, session) VALUES (?, ?, ?, ?)",
                (time.time(), role, content, session))

    # ── Read ──────────────────────────────────────────────────────────

    def get_history(self, tag: str, hours: float = 24.0,
                    max_points: int = 2000) -> List[Dict]:
        """
        Return time-series data for a sensor tag.
        Automatically decimates if too many points.
        """
        since = time.time() - hours * 3600
        with self._conn() as conn:
            total = conn.execute(
                "SELECT COUNT(*) FROM sensor_history WHERE tag=? AND ts>=?",
                (tag, since)).fetchone()[0]

            step = max(1, total // max_points)
            rows = conn.execute(
                f"""SELECT ts, value FROM sensor_history
                    WHERE tag=? AND ts>=?
                    AND rowid % ? = 0
                    ORDER BY ts ASC LIMIT ?""",
                (tag, since, step, max_points)).fetchall()

        return [{"ts": r["ts"], "value": r["value"]} for r in rows]

    def get_multi_history(self, tags: List[str], hours: float = 24.0,
                          max_points: int = 500) -> Dict[str, List[Dict]]:
        return {tag: self.get_history(tag, hours, max_points) for tag in tags}

    def get_events(self, limit: int = 100, level: Optional[str] = None,
                   hours: float = 48.0) -> List[Dict]:
        since = time.time() - hours * 3600
        with self._conn() as conn:
            if level:
                rows = conn.execute(
                    "SELECT * FROM events WHERE ts>=? AND level=? ORDER BY ts DESC LIMIT ?",
                    (since, level, limit)).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM events WHERE ts>=? ORDER BY ts DESC LIMIT ?",
                    (since, limit)).fetchall()
        return [dict(r) for r in rows]

    def get_setpoint_log(self, limit: int = 50) -> List[Dict]:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM setpoint_log ORDER BY ts DESC LIMIT ?",
                (limit,)).fetchall()
        return [dict(r) for r in rows]

    # ── Maintenance ───────────────────────────────────────────────────

    def trim_old_data(self, retention_hours: float = HISTORY_RETENTION_HOURS):
        """Delete sensor history older than retention window."""
        cutoff = time.time() - retention_hours * 3600
        with self._conn() as conn:
            deleted = conn.execute(
                "DELETE FROM sensor_history WHERE ts < ?", (cutoff,)).rowcount
        return deleted

    def get_stats(self) -> Dict[str, Any]:
        with self._conn() as conn:
            counts = {}
            for table in ("sensor_history", "events", "setpoint_log", "chat_log"):
                counts[table] = conn.execute(
                    f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        return counts
