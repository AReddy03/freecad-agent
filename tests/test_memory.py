"""
Unit tests for agent/memory.py — no FreeCAD required.
"""

import tempfile
from pathlib import Path

import pytest

from agent.memory import MemoryStore, MemoryType


@pytest.fixture
def store(tmp_path):
    """Fresh in-memory MemoryStore backed by a temp file for each test."""
    db = tmp_path / "test_memory.db"
    return MemoryStore(db_path=db)


# ---------------------------------------------------------------------------
# Schema / initialisation
# ---------------------------------------------------------------------------

def test_creates_tables(store):
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
    ).fetchone()
    assert row is not None, "memories table should exist"


def test_count_empty(store):
    assert store.count() == 0


# ---------------------------------------------------------------------------
# Save and retrieve
# ---------------------------------------------------------------------------

def test_save_returns_id(store):
    mid = store.save("User prefers metric units", MemoryType.PREFERENCE)
    assert isinstance(mid, int)
    assert mid > 0


def test_save_and_get_recent(store):
    store.save("User prefers metric units", MemoryType.PREFERENCE, importance=2.0)
    results = store.get_recent(limit=10)
    assert len(results) == 1
    assert results[0]["content"] == "User prefers metric units"
    assert results[0]["memory_type"] == "preference"


def test_count_after_save(store):
    store.save("fact one", MemoryType.FACT)
    store.save("fact two", MemoryType.FACT)
    assert store.count() == 2


def test_get_all_preferences(store):
    store.save("prefers mm", MemoryType.PREFERENCE, importance=2.0)
    store.save("session done", MemoryType.SESSION_SUMMARY)
    store.save("prefers FreeCAD Part WB", MemoryType.PREFERENCE, importance=3.0)
    prefs = store.get_all_preferences()
    assert len(prefs) == 2
    # Higher importance first
    assert prefs[0]["importance"] == 3.0


def test_get_session_summaries(store):
    store.save("built a box", MemoryType.SESSION_SUMMARY)
    store.save("prefer mm", MemoryType.PREFERENCE)
    store.save("built a cylinder", MemoryType.SESSION_SUMMARY)
    summaries = store.get_session_summaries(limit=5)
    assert len(summaries) == 2
    assert all(s["memory_type"] == "session_summary" for s in summaries)


# ---------------------------------------------------------------------------
# Search (FTS5)
# ---------------------------------------------------------------------------

def test_search_returns_relevant(store):
    store.save("User always uses millimetres for units", MemoryType.PREFERENCE)
    store.save("User likes dark mode", MemoryType.PREFERENCE)
    results = store.search("millimetres units", limit=5)
    assert len(results) >= 1
    assert any("millimetres" in r["content"] for r in results)


def test_search_with_type_filter(store):
    store.save("User prefers mm", MemoryType.PREFERENCE)
    store.save("Session: built bracket with mm", MemoryType.SESSION_SUMMARY)
    results = store.search("mm", memory_type=MemoryType.PREFERENCE, limit=5)
    assert all(r["memory_type"] == "preference" for r in results)


def test_search_empty_query_falls_back_to_recent(store):
    store.save("something", MemoryType.FACT)
    results = store.search("", limit=5)
    assert len(results) == 1


# ---------------------------------------------------------------------------
# Update / delete
# ---------------------------------------------------------------------------

def test_update_importance(store):
    mid = store.save("test fact", MemoryType.FACT, importance=1.0)
    store.update_importance(mid, 4.5)
    results = store.get_recent(limit=1)
    assert results[0]["importance"] == 4.5


def test_delete_removes_row(store):
    mid = store.save("to be deleted", MemoryType.FACT)
    assert store.count() == 1
    store.delete(mid)
    assert store.count() == 0


def test_delete_removes_from_fts(store):
    mid = store.save("unique phrase xyz123", MemoryType.FACT)
    store.delete(mid)
    results = store.search("unique phrase xyz123", limit=5)
    assert len(results) == 0


def test_increment_access(store):
    mid = store.save("track me", MemoryType.FACT)
    store.increment_access(mid)
    store.increment_access(mid)
    row = store._conn.execute(
        "SELECT access_count FROM memories WHERE id=?", (mid,)
    ).fetchone()
    assert row["access_count"] == 2


# ---------------------------------------------------------------------------
# Tags and metadata
# ---------------------------------------------------------------------------

def test_save_with_tags(store):
    mid = store.save("prefer Part WB", MemoryType.PREFERENCE, tags=["workbench", "part"])
    import json
    row = store._conn.execute(
        "SELECT metadata FROM memories WHERE id=?", (mid,)
    ).fetchone()
    meta = json.loads(row["metadata"])
    assert "workbench" in meta["tags"]


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_singleton_returns_same_instance(tmp_path):
    import agent.memory as mem_module
    # Reset singleton for isolation
    mem_module._store = None
    db = tmp_path / "singleton_test.db"
    s1 = mem_module.get_memory_store(db_path=db)
    s2 = mem_module.get_memory_store(db_path=db)
    assert s1 is s2
    mem_module._store = None  # clean up
