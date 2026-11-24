"""Local SQLite storage: cases, inputs, valuation runs, recommendations, reviews, reports and
the audit log.

The audit log is append-only (UPDATE and DELETE are refused by triggers) and hash-chained:
each entry stores the hash of the previous one, so `verify_chain` detects any edit made
outside the app."""

from __future__ import annotations

import hashlib
import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone

from valor.config import path_setting

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
  id TEXT PRIMARY KEY, deal_id TEXT, borrower_id TEXT, borrower_name TEXT, sector TEXT,
  workflow TEXT, status TEXT, created_by TEXT, created_at TEXT, updated_at TEXT,
  data_pulled_at TEXT, data_source TEXT, submitted_by TEXT, approved_by TEXT, locked INTEGER DEFAULT 0,
  deal JSON, claims JSON
);
CREATE TABLE IF NOT EXISTS case_inputs (
  case_id TEXT, key TEXT, label TEXT, unit TEXT, grp TEXT, ord INTEGER,
  value REAL, source_value REAL, source_ref TEXT, used_by TEXT, meta JSON,
  PRIMARY KEY (case_id, key)
);
CREATE TABLE IF NOT EXISTS pulled_tables (case_id TEXT, name TEXT, data JSON, PRIMARY KEY (case_id, name));
CREATE TABLE IF NOT EXISTS valuation_runs (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, actor TEXT, inputs_hash TEXT,
  results JSON, checks JSON, engine_versions JSON, explanation TEXT, explanation_source TEXT
);
CREATE TABLE IF NOT EXISTS recommendations (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, run_id INTEGER, ts TEXT, source TEXT,
  kind TEXT, field TEXT, title TEXT, rationale TEXT, severity TEXT,
  current_value REAL, proposed_value REAL, status TEXT DEFAULT 'open',
  decided_by TEXT, decided_at TEXT, final_value REAL, decision_note TEXT
);
CREATE TABLE IF NOT EXISTS agent_runs (
  id TEXT PRIMARY KEY, case_id TEXT, ts TEXT, task TEXT, mode TEXT, model TEXT, duration_s REAL,
  status TEXT, prompt_hash TEXT, output_path TEXT, error TEXT, cost_usd REAL
);
CREATE TABLE IF NOT EXISTS reviews (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, actor TEXT, action TEXT, comment TEXT
);
CREATE TABLE IF NOT EXISTS reports (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, actor TEXT, template TEXT,
  html_path TEXT, docx_path TEXT, md_path TEXT, findings JSON, findings_hash TEXT, narrative_source TEXT,
  external_url TEXT
);
CREATE TABLE IF NOT EXISTS challenges (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, raised_by TEXT, run_id INTEGER,
  field TEXT, label TEXT, unit TEXT, analyst_value REAL, proposed_value REAL, comment TEXT, impact JSON,
  status TEXT DEFAULT 'open', response TEXT, resolved_by TEXT, resolved_at TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
  id INTEGER PRIMARY KEY AUTOINCREMENT, case_id TEXT, ts TEXT, actor TEXT, event TEXT,
  field TEXT, label TEXT, old_value TEXT, new_value TEXT, source_value TEXT, rationale TEXT,
  details JSON, prev_hash TEXT, hash TEXT
);
CREATE TRIGGER IF NOT EXISTS audit_no_update BEFORE UPDATE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
CREATE TRIGGER IF NOT EXISTS audit_no_delete BEFORE DELETE ON audit_log
  BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END;
"""

MIGRATIONS = ["extras JSON", "opinion JSON"]

_lock = threading.RLock()
_initialized: set[str] = set()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def db_path():
    p = path_setting("storage", "sqlite_path")
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


@contextmanager
def conn():
    path = str(db_path())
    with _lock:
        c = sqlite3.connect(path)
        c.row_factory = sqlite3.Row
        if path not in _initialized:
            c.executescript(SCHEMA)
            for col in MIGRATIONS:                       # add columns introduced after a DB was created
                try:
                    c.execute(f"ALTER TABLE cases ADD COLUMN {col}")
                except sqlite3.OperationalError:
                    pass
            _initialized.add(path)
        try:
            yield c
            c.commit()
        finally:
            c.close()


def rows(sql: str, params=()) -> list[dict]:
    with conn() as c:
        return [dict(r) for r in c.execute(sql, params).fetchall()]


def one(sql: str, params=()) -> dict | None:
    r = rows(sql, params)
    return r[0] if r else None


def execute(sql: str, params=()) -> int:
    with conn() as c:
        cur = c.execute(sql, params)
        return cur.lastrowid


# ── audit ─────────────────────────────────────────────────────────────

def _entry_hash(prev: str, e: dict) -> str:
    body = json.dumps({k: e.get(k) for k in ("case_id", "ts", "actor", "event", "field", "old_value", "new_value",
                                             "source_value", "rationale", "details")}, sort_keys=True, default=str)
    return hashlib.sha256((prev + body).encode()).hexdigest()


def audit(case_id: str, actor: str, event: str, *, field=None, label=None, old=None, new=None, source=None,
          rationale=None, details: dict | None = None) -> None:
    with conn() as c:
        last = c.execute("SELECT hash FROM audit_log ORDER BY id DESC LIMIT 1").fetchone()
        prev = last["hash"] if last else "genesis"
        e = {"case_id": case_id, "ts": now(), "actor": actor, "event": event, "field": field, "label": label,
             "old_value": None if old is None else str(old), "new_value": None if new is None else str(new),
             "source_value": None if source is None else str(source), "rationale": rationale,
             "details": json.dumps(details, default=str) if details else None}
        e["prev_hash"] = prev
        e["hash"] = _entry_hash(prev, e)
        c.execute("INSERT INTO audit_log (case_id, ts, actor, event, field, label, old_value, new_value, source_value, "
                  "rationale, details, prev_hash, hash) VALUES (:case_id, :ts, :actor, :event, :field, :label, :old_value, "
                  ":new_value, :source_value, :rationale, :details, :prev_hash, :hash)", e)


def audit_trail(case_id: str | None = None) -> list[dict]:
    if case_id:
        return rows("SELECT * FROM audit_log WHERE case_id = ? ORDER BY id", (case_id,))
    return rows("SELECT * FROM audit_log ORDER BY id")


def verify_chain() -> dict:
    prev, n = "genesis", 0
    for e in rows("SELECT * FROM audit_log ORDER BY id"):
        if e["prev_hash"] != prev or _entry_hash(prev, e) != e["hash"]:
            return {"ok": False, "entries": n, "broken_at": e["id"]}
        prev, n = e["hash"], n + 1
    return {"ok": True, "entries": n, "head": prev[:12]}
