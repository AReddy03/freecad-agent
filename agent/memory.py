"""
Cross-session memory store for the FreeCAD agent.

Persists memories to ~/.freecad-agent/memory.db using SQLite FTS5.
Zero new dependencies — sqlite3 is stdlib.

Usage:
    from agent.memory import get_memory_store, MemoryType

    ms = get_memory_store()
    ms.save("User prefers metric units", MemoryType.PREFERENCE, importance=2.0)
    results = ms.search("units preferences", limit=5)
"""

import json
import sqlite3
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DEFAULT_DB = Path.home() / ".freecad-agent" / "memory.db"

_CREATE_MEMORIES = """
CREATE TABLE IF NOT EXISTS memories (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    memory_type  TEXT    NOT NULL,
    content      TEXT    NOT NULL,
    metadata     TEXT    NOT NULL DEFAULT '{}',
    importance   REAL    NOT NULL DEFAULT 1.0,
    created_at   TEXT    NOT NULL,
    updated_at   TEXT    NOT NULL,
    access_count INTEGER NOT NULL DEFAULT 0
);
"""

_CREATE_FTS = """
CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts
    USING fts5(content, memory_type, content='memories', content_rowid='id');
"""

_CREATE_FTS_TRIGGERS = """
CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
    INSERT INTO memories_fts(rowid, content, memory_type)
    VALUES (new.id, new.content, new.memory_type);
END;
CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, memory_type)
    VALUES ('delete', old.id, old.content, old.memory_type);
END;
CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
    INSERT INTO memories_fts(memories_fts, rowid, content, memory_type)
    VALUES ('delete', old.id, old.content, old.memory_type);
    INSERT INTO memories_fts(rowid, content, memory_type)
    VALUES (new.id, new.content, new.memory_type);
END;
"""


# ---------------------------------------------------------------------------
# MemoryType enum
# ---------------------------------------------------------------------------

class MemoryType(str, Enum):
    PREFERENCE      = "preference"       # units, naming style, favourite workbench
    SCRIPT_PATTERN  = "script_pattern"   # successful reusable script snippets
    SESSION_SUMMARY = "session_summary"  # what was accomplished in a past session
    FACT            = "fact"             # anything else the agent wants to remember


# ---------------------------------------------------------------------------
# MemoryStore
# ---------------------------------------------------------------------------

class MemoryStore:
    """SQLite-backed persistent memory store with FTS5 full-text search."""

    def __init__(self, db_path: Path = _DEFAULT_DB):
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(
            str(db_path),
            check_same_thread=False,
            detect_types=sqlite3.PARSE_DECLTYPES,
        )
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL;")
        self._conn.execute("PRAGMA foreign_keys=ON;")
        self._setup()

    # -----------------------------------------------------------------------
    # Schema setup
    # -----------------------------------------------------------------------

    def _setup(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(_CREATE_MEMORIES)
        cur.executescript(_CREATE_FTS)
        cur.executescript(_CREATE_FTS_TRIGGERS)
        self._conn.commit()

    # -----------------------------------------------------------------------
    # Write
    # -----------------------------------------------------------------------

    def save(
        self,
        content: str,
        memory_type: MemoryType,
        importance: float = 1.0,
        tags: Optional[list] = None,
        session_id: str = "",
        source: str = "agent",
    ) -> int:
        """Insert a new memory; return its row id."""
        now = datetime.now(timezone.utc).isoformat()
        metadata = json.dumps({
            "session_id": session_id,
            "tags": tags or [],
            "source": source,
        })
        cur = self._conn.cursor()
        cur.execute(
            """INSERT INTO memories
               (memory_type, content, metadata, importance, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (memory_type.value, content, metadata, importance, now, now),
        )
        self._conn.commit()
        return cur.lastrowid

    def update_importance(self, memory_id: int, importance: float) -> None:
        now = datetime.now(timezone.utc).isoformat()
        self._conn.execute(
            "UPDATE memories SET importance=?, updated_at=? WHERE id=?",
            (importance, now, memory_id),
        )
        self._conn.commit()

    def delete(self, memory_id: int) -> None:
        self._conn.execute("DELETE FROM memories WHERE id=?", (memory_id,))
        self._conn.commit()

    def increment_access(self, memory_id: int) -> None:
        self._conn.execute(
            "UPDATE memories SET access_count=access_count+1 WHERE id=?",
            (memory_id,),
        )
        self._conn.commit()

    # -----------------------------------------------------------------------
    # Read
    # -----------------------------------------------------------------------

    def search(
        self,
        query: str,
        memory_type: Optional[MemoryType] = None,
        limit: int = 5,
    ) -> list[dict]:
        """FTS5 full-text search, ranked by relevance × importance."""
        if not query.strip():
            return self.get_recent(memory_type=memory_type, limit=limit)

        # Sanitise query for FTS5 (strip special chars that could break the parser)
        fts_query = " ".join(
            w for w in query.split() if w.isalnum() or len(w) > 2
        ) or query[:50]

        try:
            if memory_type:
                rows = self._conn.execute(
                    """SELECT m.id, m.memory_type, m.content, m.metadata,
                              m.importance, m.created_at, m.access_count
                       FROM memories m
                       JOIN memories_fts f ON f.rowid = m.id
                       WHERE memories_fts MATCH ? AND m.memory_type = ?
                       ORDER BY rank * m.importance
                       LIMIT ?""",
                    (fts_query, memory_type.value, limit),
                ).fetchall()
            else:
                rows = self._conn.execute(
                    """SELECT m.id, m.memory_type, m.content, m.metadata,
                              m.importance, m.created_at, m.access_count
                       FROM memories m
                       JOIN memories_fts f ON f.rowid = m.id
                       WHERE memories_fts MATCH ?
                       ORDER BY rank * m.importance
                       LIMIT ?""",
                    (fts_query, limit),
                ).fetchall()
        except sqlite3.OperationalError:
            # FTS5 query parse error — fall back to recency
            return self.get_recent(memory_type=memory_type, limit=limit)

        return [dict(r) for r in rows]

    def get_recent(
        self,
        memory_type: Optional[MemoryType] = None,
        limit: int = 10,
    ) -> list[dict]:
        """Return most recent memories, optionally filtered by type."""
        if memory_type:
            rows = self._conn.execute(
                """SELECT id, memory_type, content, metadata, importance, created_at, access_count
                   FROM memories WHERE memory_type=?
                   ORDER BY importance DESC, updated_at DESC
                   LIMIT ?""",
                (memory_type.value, limit),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """SELECT id, memory_type, content, metadata, importance, created_at, access_count
                   FROM memories
                   ORDER BY importance DESC, updated_at DESC
                   LIMIT ?""",
                (limit,),
            ).fetchall()
        return [dict(r) for r in rows]

    def get_all_preferences(self) -> list[dict]:
        """All PREFERENCE memories sorted by importance."""
        return self.get_recent(memory_type=MemoryType.PREFERENCE, limit=20)

    def get_session_summaries(self, limit: int = 5) -> list[dict]:
        """Most recent SESSION_SUMMARY memories."""
        return self.get_recent(memory_type=MemoryType.SESSION_SUMMARY, limit=limit)

    def count(self) -> int:
        """Total number of memories."""
        row = self._conn.execute("SELECT COUNT(*) FROM memories").fetchone()
        return row[0] if row else 0

    def close(self) -> None:
        self._conn.close()


# ---------------------------------------------------------------------------
# Singleton helper
# ---------------------------------------------------------------------------

_store: Optional[MemoryStore] = None


def get_memory_store(db_path: Path = _DEFAULT_DB) -> MemoryStore:
    """Return a module-level singleton MemoryStore."""
    global _store
    if _store is None:
        _store = MemoryStore(db_path)
    return _store
