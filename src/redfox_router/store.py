"""SQLite store for router telemetry: events, health, quota snapshots, incidents."""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from pathlib import Path

DEFAULT_DB = Path(os.environ.get(
    "REDFOX_ROUTER_DB",
    str(Path(__file__).resolve().parents[2] / "data" / "router.db"),
))


def _now() -> float:
    return time.time()


class RouterStore:
    def __init__(self, db_path: str | Path | None = None):
        self.db_path = Path(db_path) if db_path else DEFAULT_DB
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._ensure_schema()

    def _ensure_schema(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS request_events(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ts REAL, logical_model TEXT, backend_id TEXT, upstream_model TEXT,
                    http_status INTEGER, failure_class TEXT, latency_ms INTEGER,
                    retry_after_s REAL, error_excerpt TEXT, attempt INTEGER);
                CREATE TABLE IF NOT EXISTS backend_health(
                    backend_id TEXT PRIMARY KEY, state TEXT, consecutive_failures INTEGER,
                    last_ok_at REAL, last_error_at REAL, last_failure_class TEXT,
                    cooldown_until REAL, updated_at REAL);
                CREATE TABLE IF NOT EXISTS quota_snapshots(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    backend_id TEXT, observed_at REAL, source TEXT,
                    rpm_limit INTEGER, rpm_remaining INTEGER, rpm_reset_s REAL,
                    rpd_limit INTEGER, rpd_remaining INTEGER, rpd_reset_s REAL,
                    raw_json TEXT, confidence TEXT);
                CREATE TABLE IF NOT EXISTS incidents(
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    opened_at REAL, backend_id TEXT, severity TEXT,
                    failure_class TEXT, summary TEXT);
                """
            )
            self._conn.commit()

    # ── events ────────────────────────────────────────────────────────────
    def record_event(self, logical_model: str, backend_id: str, upstream_model: str,
                     http_status: int | None, failure_class: str, latency_ms: int,
                     retry_after_s: float | None = None, error_excerpt: str = "",
                     attempt: int = 0) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO request_events(ts,logical_model,backend_id,upstream_model,
                   http_status,failure_class,latency_ms,retry_after_s,error_excerpt,attempt)
                   VALUES(?,?,?,?,?,?,?,?,?,?)""",
                (_now(), logical_model, backend_id, upstream_model, http_status,
                 failure_class, latency_ms, retry_after_s, error_excerpt[:300], attempt),
            )
            self._conn.commit()

    def record_snapshot(self, backend_id: str, headers: dict, source: str = "headers",
                        confidence: str = "high") -> None:
        def gi(name):
            v = headers.get(name)
            try:
                return int(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        def gf(name):
            v = headers.get(name)
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        with self._lock:
            self._conn.execute(
                """INSERT INTO quota_snapshots(backend_id,observed_at,source,rpm_limit,
                   rpm_remaining,rpm_reset_s,rpd_limit,rpd_remaining,rpd_reset_s,raw_json,confidence)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (backend_id, _now(), source,
                 gi("x-ratelimit-limit-minute"), gi("x-ratelimit-remaining-minute"),
                 gf("x-ratelimit-reset-minute"),
                 gi("x-ratelimit-limit-day"), gi("x-ratelimit-remaining-day"),
                 gf("x-ratelimit-reset-day"),
                 json.dumps({k: v for k, v in headers.items() if "ratelimit" in k.lower()}),
                 confidence),
            )
            self._conn.commit()

    # ── health ────────────────────────────────────────────────────────────
    def health(self, backend_id: str) -> dict:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM backend_health WHERE backend_id=?", (backend_id,)
            ).fetchone()
        if row is None:
            return {"backend_id": backend_id, "state": "healthy", "consecutive_failures": 0,
                    "cooldown_until": 0.0, "last_ok_at": None, "last_error_at": None,
                    "last_failure_class": None}
        return dict(row)

    def record_success(self, backend_id: str) -> None:
        with self._lock:
            self._conn.execute(
                """INSERT INTO backend_health(backend_id,state,consecutive_failures,last_ok_at,
                   last_error_at,last_failure_class,cooldown_until,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(backend_id) DO UPDATE SET
                     state='healthy', consecutive_failures=0, last_ok_at=excluded.last_ok_at,
                     cooldown_until=0, updated_at=excluded.updated_at""",
                (backend_id, "healthy", 0, _now(), None, None, 0.0, _now()),
            )
            self._conn.commit()

    def record_failure(self, backend_id: str, failure_class: str, cooldown_s: float,
                       summary: str = "") -> None:
        with self._lock:
            prev = self._conn.execute(
                "SELECT consecutive_failures FROM backend_health WHERE backend_id=?", (backend_id,)
            ).fetchone()
            cf = (prev["consecutive_failures"] if prev else 0) + 1
            state = "down" if cf >= 3 else "cooldown"
            self._conn.execute(
                """INSERT INTO backend_health(backend_id,state,consecutive_failures,last_ok_at,
                   last_error_at,last_failure_class,cooldown_until,updated_at)
                   VALUES(?,?,?,?,?,?,?,?)
                   ON CONFLICT(backend_id) DO UPDATE SET
                     state=excluded.state, consecutive_failures=excluded.consecutive_failures,
                     last_error_at=excluded.last_error_at, last_failure_class=excluded.last_failure_class,
                     cooldown_until=excluded.cooldown_until, updated_at=excluded.updated_at""",
                (backend_id, state, cf, None, _now(), failure_class, _now() + cooldown_s, _now()),
            )
            self._conn.execute(
                "INSERT INTO incidents(opened_at,backend_id,severity,failure_class,summary) VALUES(?,?,?,?,?)",
                (_now(), backend_id, state, failure_class, summary[:300]),
            )
            self._conn.commit()

    def in_cooldown(self, backend_id: str) -> float:
        """Seconds left of cooldown (0 if none/expired)."""
        h = self.health(backend_id)
        until = h.get("cooldown_until") or 0.0
        return max(0.0, until - _now())

    # ── views ─────────────────────────────────────────────────────────────
    def latest_snapshot(self, backend_id: str) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM quota_snapshots WHERE backend_id=? ORDER BY id DESC LIMIT 1",
                (backend_id,),
            ).fetchone()
        return dict(row) if row else None

    def recent_incidents(self, limit: int = 10) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM incidents ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM request_events ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) c FROM request_events").fetchone()["c"]
            fails = self._conn.execute(
                "SELECT COUNT(*) c FROM request_events WHERE failure_class!='ok'").fetchone()["c"]
        return {"events": total, "failures": fails}
