"""
Transactional memory: a durable, append-only, hash-chained audit log of every
agent-driven action.

Persists to ~/.freecad-agent/audit.db using stdlib sqlite3. Unlike
agent/memory.py's MemoryStore, records are never updated or deleted — each
row's hash is chained to the previous row's hash (sha256), so tampering or
deletion is detectable by recomputing the chain with verify_chain().

Usage:
    from agent.audit import get_audit_store, AuditEventType

    store = get_audit_store()
    store.record(AuditEventType.TOOL_CALL_STARTED, thread_id="t1", turn_index=0,
                 tool_name="execute_script", tool_call_id="call_1", payload={"args": {...}})
    result = store.verify_chain()
"""

import hashlib
import json
import sqlite3
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path.home() / ".freecad-agent" / "audit.db"

_GENESIS_HASH = "0" * 64

_CREATE_AUDIT_LOG = """
CREATE TABLE IF NOT EXISTS audit_log (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    thread_id     TEXT    NOT NULL,
    turn_index    INTEGER NOT NULL,
    event_type    TEXT    NOT NULL,
    tool_name     TEXT,
    tool_call_id  TEXT,
    payload       TEXT    NOT NULL DEFAULT '{}',
    created_at    TEXT    NOT NULL,
    prev_hash     TEXT    NOT NULL,
    record_hash   TEXT    NOT NULL UNIQUE
);
"""

_CREATE_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_audit_thread_turn
    ON audit_log(thread_id, turn_index);
CREATE INDEX IF NOT EXISTS idx_audit_dedup
    ON audit_log(thread_id, turn_index, tool_call_id, event_type);
"""


# ---------------------------------------------------------------------------
# AuditEventType enum
# ---------------------------------------------------------------------------

class AuditEventType(str, Enum):
    TOOL_CALL_STARTED      = "tool_call_started"
    TOOL_CALL_COMPLETED    = "tool_call_completed"
    TOOL_CALL_FAILED       = "tool_call_failed"
    CONFIRMATION_REQUESTED = "confirmation_requested"
    CONFIRMATION_RESOLVED  = "confirmation_resolved"
    STEP_LIMIT_HALT        = "step_limit_halt"


# ---------------------------------------------------------------------------
# ChainVerification result
# ---------------------------------------------------------------------------

@dataclass
class ChainVerification:
    valid: bool
    checked: int
    first_invalid_id: Optional[int] = None
    reason: str = ""


# ---------------------------------------------------------------------------
# Hashing
# ---------------------------------------------------------------------------

def _canonical(fields: dict) -> str:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)


def _record_hash(prev_hash: str, fields: dict) -> str:
    return hashlib.sha256((prev_hash + _canonical(fields)).encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# AuditStore
# ---------------------------------------------------------------------------

class AuditStore:
    """SQLite-backed, append-only, hash-chained action log."""

    def __init__(self, db_path: Path = _DEFAULT_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._lock = threading.Lock()
        self._setup()

    def _setup(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(_CREATE_AUDIT_LOG)
        cur.executescript(_CREATE_INDEXES)
        self._conn.commit()

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def _last_hash(self) -> str:
        row = self._conn.execute(
            "SELECT record_hash FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return row["record_hash"] if row else _GENESIS_HASH

    def _row_to_dict(self, row: sqlite3.Row) -> dict:
        d = dict(row)
        try:
            d["payload"] = json.loads(d["payload"])
        except (TypeError, ValueError):
            # Only reachable if the row was tampered with; verify_chain() is
            # what reports that, so surface the raw text rather than raising.
            pass
        return d

    def _append_locked(self, entries: list[dict], thread_id: str, turn_index: int) -> list[dict]:
        """
        Append entries as one chained transaction — a single commit for the whole
        batch, so an N-call tool batch costs one fsync instead of N.

        Caller must hold self._lock: the chain's prev_hash is read-then-written,
        so check-and-append has to be atomic against other sessions.
        """
        cur = self._conn.cursor()
        prev_hash = self._last_hash()
        rows = []

        try:
            for entry in entries:
                event_type = entry["event_type"]
                payload = entry.get("payload") or {}
                # Serialised exactly once: this same string is what gets stored
                # and what the hash covers, so verify_chain() can hash the stored
                # bytes directly instead of re-serialising every row.
                payload_json = _canonical(payload)
                now = datetime.now(timezone.utc).isoformat()
                fields = {
                    "thread_id": thread_id,
                    "turn_index": turn_index,
                    "event_type": event_type.value,
                    "tool_name": entry.get("tool_name"),
                    "tool_call_id": entry.get("tool_call_id"),
                    "payload": payload_json,
                    "created_at": now,
                }
                record_hash = _record_hash(prev_hash, fields)
                cur.execute(
                    """INSERT INTO audit_log
                       (thread_id, turn_index, event_type, tool_name, tool_call_id,
                        payload, created_at, prev_hash, record_hash)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (thread_id, turn_index, event_type.value, fields["tool_name"],
                     fields["tool_call_id"], payload_json, now, prev_hash, record_hash),
                )
                rows.append({
                    **fields,
                    "id": cur.lastrowid,
                    "payload": payload,
                    "prev_hash": prev_hash,
                    "record_hash": record_hash,
                })
                prev_hash = record_hash
        except Exception:
            # Callers deliberately swallow audit failures, so a half-written
            # batch left open here would be committed by whoever writes next.
            self._conn.rollback()
            raise

        self._conn.commit()
        return rows

    def record(
        self,
        event_type: AuditEventType,
        thread_id: str,
        turn_index: int,
        tool_name: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> dict:
        """Append one record to the chain; returns the inserted row."""
        entry = {
            "event_type": event_type,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "payload": payload,
        }
        with self._lock:
            return self._append_locked([entry], thread_id, turn_index)[0]

    def record_many(self, entries: list[dict], thread_id: str, turn_index: int) -> list[dict]:
        """
        Append several records sharing a thread/turn in one transaction.

        Each entry is a dict of {"event_type": AuditEventType, "tool_name": str|None,
        "tool_call_id": str|None, "payload": dict|None}.
        """
        if not entries:
            return []
        with self._lock:
            return self._append_locked(entries, thread_id, turn_index)

    def record_once(
        self,
        event_type: AuditEventType,
        thread_id: str,
        turn_index: int,
        tool_call_id: str,
        tool_name: Optional[str] = None,
        payload: Optional[dict] = None,
    ) -> dict:
        """
        Idempotent variant keyed on (thread_id, turn_index, tool_call_id, event_type).

        If a matching row already exists, returns it unchanged (no new chain
        entry). Otherwise behaves exactly like record(). Safe to call from code
        LangGraph may re-run from the top on interrupt() resume. The lookup and
        the append share one lock acquisition, so concurrent callers can't both
        miss the check and write a duplicate.
        """
        entry = {
            "event_type": event_type,
            "tool_name": tool_name,
            "tool_call_id": tool_call_id,
            "payload": payload,
        }
        with self._lock:
            existing = self._conn.execute(
                """SELECT * FROM audit_log
                   WHERE thread_id=? AND turn_index=? AND tool_call_id=? AND event_type=?
                   ORDER BY id ASC LIMIT 1""",
                (thread_id, turn_index, tool_call_id, event_type.value),
            ).fetchone()
            if existing is not None:
                return self._row_to_dict(existing)
            return self._append_locked([entry], thread_id, turn_index)[0]

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def get_events(
        self,
        thread_id: Optional[str] = None,
        event_type: Optional[AuditEventType] = None,
        limit: int = 100,
    ) -> list[dict]:
        """Most-recent-first, optionally filtered by thread and/or event type."""
        clauses = []
        params: list = []
        if thread_id is not None:
            clauses.append("thread_id=?")
            params.append(thread_id)
        if event_type is not None:
            clauses.append("event_type=?")
            params.append(event_type.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        params.append(limit)
        rows = self._conn.execute(
            f"SELECT * FROM audit_log {where} ORDER BY id DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def verify_chain(self) -> ChainVerification:
        """
        Recompute every record_hash in id order and compare to what's stored.

        Streams the cursor rather than materialising the table: this log is
        append-only and never pruned, so it must not be loaded into memory
        wholesale to be checked.
        """
        cursor = self._conn.execute("SELECT * FROM audit_log ORDER BY id ASC")

        expected_prev = _GENESIS_HASH
        checked = 0
        for row in cursor:
            if row["prev_hash"] != expected_prev:
                return ChainVerification(
                    valid=False, checked=checked, first_invalid_id=row["id"],
                    reason="prev_hash does not match the preceding record's hash "
                           "(row deleted, reordered, or inserted out of band)",
                )
            fields = {
                "thread_id": row["thread_id"],
                "turn_index": row["turn_index"],
                "event_type": row["event_type"],
                "tool_name": row["tool_name"],
                "tool_call_id": row["tool_call_id"],
                "payload": row["payload"],
                "created_at": row["created_at"],
            }
            if _record_hash(row["prev_hash"], fields) != row["record_hash"]:
                return ChainVerification(
                    valid=False, checked=checked, first_invalid_id=row["id"],
                    reason="record_hash does not match its recomputed value "
                           "(row content was modified in place)",
                )
            expected_prev = row["record_hash"]
            checked += 1

        return ChainVerification(valid=True, checked=checked)

    def count(self) -> int:
        row = self._conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_store: Optional[AuditStore] = None
_store_lock = threading.Lock()


def get_audit_store(db_path: Path = _DEFAULT_DB) -> AuditStore:
    """Return a module-level singleton AuditStore."""
    global _store
    with _store_lock:
        if _store is None:
            _store = AuditStore(db_path)
        return _store
