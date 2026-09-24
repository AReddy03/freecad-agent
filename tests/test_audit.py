"""
Unit tests for agent/audit.py — no FreeCAD required.
"""

import json

import pytest

from agent.audit import AuditEventType, AuditStore


@pytest.fixture
def store(tmp_path):
    """Fresh AuditStore backed by a temp file for each test."""
    db = tmp_path / "test_audit.db"
    return AuditStore(db_path=db)


# ---------------------------------------------------------------------------
# Schema / initialisation
# ---------------------------------------------------------------------------

def test_creates_table(store):
    row = store._conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='audit_log'"
    ).fetchone()
    assert row is not None, "audit_log table should exist"


def test_count_empty(store):
    assert store.count() == 0


# ---------------------------------------------------------------------------
# record()
# ---------------------------------------------------------------------------

def test_record_returns_row_with_hash(store):
    row = store.record(
        AuditEventType.TOOL_CALL_STARTED, thread_id="t1", turn_index=0,
        tool_name="execute_script", tool_call_id="call_1", payload={"args": {"code": "x"}},
    )
    assert len(row["record_hash"]) == 64
    assert row["prev_hash"] == "0" * 64
    assert row["payload"] == {"args": {"code": "x"}}


def test_count_after_record(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    assert store.count() == 2


def test_hash_chain_links_sequential_records(store):
    row1 = store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    row2 = store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    assert row2["prev_hash"] == row1["record_hash"]
    assert row2["record_hash"] != row1["record_hash"]


# ---------------------------------------------------------------------------
# record_many()
# ---------------------------------------------------------------------------

def test_record_many_chains_every_row(store):
    rows = store.record_many(
        [
            {"event_type": AuditEventType.TOOL_CALL_STARTED, "tool_name": "a", "tool_call_id": "c1"},
            {"event_type": AuditEventType.TOOL_CALL_STARTED, "tool_name": "b", "tool_call_id": "c2"},
            {"event_type": AuditEventType.TOOL_CALL_STARTED, "tool_name": "c", "tool_call_id": "c3"},
        ],
        thread_id="t1", turn_index=0,
    )
    assert len(rows) == 3
    assert store.count() == 3
    assert rows[0]["prev_hash"] == "0" * 64
    assert rows[1]["prev_hash"] == rows[0]["record_hash"]
    assert rows[2]["prev_hash"] == rows[1]["record_hash"]
    assert store.verify_chain().valid is True


def test_record_many_empty_is_a_no_op(store):
    assert store.record_many([], thread_id="t1", turn_index=0) == []
    assert store.count() == 0


def test_failed_batch_leaves_nothing_behind(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")

    # Second entry has no event_type, so the batch raises partway through.
    with pytest.raises(Exception):
        store.record_many(
            [
                {"event_type": AuditEventType.TOOL_CALL_STARTED, "tool_name": "b", "tool_call_id": "c2"},
                {"tool_name": "broken"},
            ],
            thread_id="t1", turn_index=0,
        )

    # The partial row must be rolled back, not left pending for the next commit.
    assert store.count() == 1
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    assert store.count() == 2
    assert store.verify_chain().valid is True


def test_record_many_interleaves_with_record(store):
    store.record(AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c1")
    store.record_many(
        [{"event_type": AuditEventType.TOOL_CALL_STARTED, "tool_name": "a", "tool_call_id": "c1"}],
        thread_id="t1", turn_index=0,
    )
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_call_id="c1")
    assert store.count() == 3
    assert store.verify_chain().valid is True


# ---------------------------------------------------------------------------
# record_once()
# ---------------------------------------------------------------------------

def test_record_once_dedupes_by_key(store):
    row1 = store.record_once(
        AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c1", tool_name="clear_document",
    )
    row2 = store.record_once(
        AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c1", tool_name="clear_document",
    )
    assert store.count() == 1
    assert row1["id"] == row2["id"]
    assert row1["record_hash"] == row2["record_hash"]


def test_record_once_distinguishes_different_tool_call_ids(store):
    store.record_once(AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c1")
    store.record_once(AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c2")
    assert store.count() == 2


def test_record_once_distinguishes_different_event_types(store):
    store.record_once(AuditEventType.CONFIRMATION_REQUESTED, "t1", 0, tool_call_id="c1")
    store.record(AuditEventType.CONFIRMATION_RESOLVED, "t1", 0, tool_call_id="c1")
    assert store.count() == 2


# ---------------------------------------------------------------------------
# verify_chain()
# ---------------------------------------------------------------------------

def test_verify_chain_valid_on_empty_store(store):
    result = store.verify_chain()
    assert result.valid is True
    assert result.checked == 0


def test_verify_chain_valid_on_fresh_writes(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.STEP_LIMIT_HALT, "t1", 1, payload={"max_iterations": 20})
    result = store.verify_chain()
    assert result.valid is True
    assert result.checked == 3


def test_verify_chain_detects_in_place_tampering(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")

    store._conn.execute(
        "UPDATE audit_log SET payload=? WHERE id=1", (json.dumps({"tampered": True}),)
    )
    store._conn.commit()

    result = store.verify_chain()
    assert result.valid is False
    assert result.first_invalid_id == 1


def test_verify_chain_detects_deleted_row(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.STEP_LIMIT_HALT, "t1", 1)

    store._conn.execute("DELETE FROM audit_log WHERE id=2")
    store._conn.commit()

    result = store.verify_chain()
    assert result.valid is False
    assert result.first_invalid_id == 3


# ---------------------------------------------------------------------------
# get_events()
# ---------------------------------------------------------------------------

def test_get_events_filters_by_thread_and_type(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_STARTED, "t2", 0, tool_name="b", tool_call_id="c2")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")

    t1_events = store.get_events(thread_id="t1")
    assert len(t1_events) == 2
    assert all(e["thread_id"] == "t1" for e in t1_events)

    started_only = store.get_events(event_type=AuditEventType.TOOL_CALL_STARTED)
    assert len(started_only) == 2
    assert all(e["event_type"] == "tool_call_started" for e in started_only)


def test_get_events_most_recent_first(store):
    store.record(AuditEventType.TOOL_CALL_STARTED, "t1", 0, tool_name="a", tool_call_id="c1")
    store.record(AuditEventType.TOOL_CALL_COMPLETED, "t1", 0, tool_name="a", tool_call_id="c1")
    events = store.get_events(thread_id="t1")
    assert events[0]["event_type"] == "tool_call_completed"
    assert events[1]["event_type"] == "tool_call_started"


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

def test_singleton_returns_same_instance(tmp_path):
    import agent.audit as audit_module
    audit_module._store = None
    db = tmp_path / "singleton_test.db"
    s1 = audit_module.get_audit_store(db_path=db)
    s2 = audit_module.get_audit_store(db_path=db)
    assert s1 is s2
    audit_module._store = None
