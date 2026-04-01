"""
Unit tests for agent/state.py and agent/prompts.py.
No FreeCAD instance required.
"""

import pytest
from agent.state import append_features, make_feature_entry
from agent.prompts import format_feature_tree_context, _MAX_CHARS, _MAX_ENTRIES


# ---------------------------------------------------------------------------
# make_feature_entry
# ---------------------------------------------------------------------------

def test_make_feature_entry_has_required_keys():
    entry = make_feature_entry("Box", "Part::Box", "my_box", "Created my_box [Part::Box]", 1)
    for key in ("name", "type_id", "label", "operation_summary", "turn_index", "timestamp", "valid"):
        assert key in entry, f"Missing key: {key}"


def test_make_feature_entry_valid_by_default():
    entry = make_feature_entry("Box", "Part::Box", "box", "Created box", 1)
    assert entry["valid"] is True


def test_make_feature_entry_timestamp_is_string():
    entry = make_feature_entry("Box", "Part::Box", "box", "Created box", 1)
    assert isinstance(entry["timestamp"], str)
    assert "T" in entry["timestamp"]  # ISO 8601


def test_make_feature_entry_values():
    entry = make_feature_entry("Cyl001", "Part::Cylinder", "my_cyl", "Created cylinder", 3)
    assert entry["name"] == "Cyl001"
    assert entry["type_id"] == "Part::Cylinder"
    assert entry["label"] == "my_cyl"
    assert entry["turn_index"] == 3


# ---------------------------------------------------------------------------
# append_features reducer
# ---------------------------------------------------------------------------

def test_append_features_concatenates():
    a = [make_feature_entry("Box", "Part::Box", "box", "Created box", 1)]
    b = [make_feature_entry("Cyl", "Part::Cylinder", "cyl", "Created cyl", 2)]
    result = append_features(a, b)
    assert len(result) == 2
    assert result[0]["name"] == "Box"
    assert result[1]["name"] == "Cyl"


def test_append_features_does_not_drop_existing():
    existing = [make_feature_entry(f"Obj{i}", "Part::Box", f"obj{i}", "x", i) for i in range(5)]
    new = [make_feature_entry("New", "Part::Sphere", "new", "y", 6)]
    result = append_features(existing, new)
    assert len(result) == 6
    assert result[-1]["name"] == "New"


def test_append_features_empty_new():
    existing = [make_feature_entry("Box", "Part::Box", "box", "x", 1)]
    result = append_features(existing, [])
    assert result == existing


def test_append_features_empty_existing():
    new = [make_feature_entry("Box", "Part::Box", "box", "x", 1)]
    result = append_features([], new)
    assert result == new


# ---------------------------------------------------------------------------
# format_feature_tree_context
# ---------------------------------------------------------------------------

def test_format_empty_tree():
    out = format_feature_tree_context([])
    assert "No objects created yet" in out
    assert "Current document state" in out


def test_format_single_entry():
    tree = [make_feature_entry("Box", "Part::Box", "my_box", "Created my_box [Part::Box]", 1)]
    out = format_feature_tree_context(tree)
    assert "my_box" in out
    assert "Part::Box" in out
    assert "T1" in out


def test_format_shows_turn_index():
    tree = [make_feature_entry("Sph", "Part::Sphere", "sph", "Created sph", 5)]
    out = format_feature_tree_context(tree)
    assert "T5" in out


def test_format_truncates_at_max_entries():
    tree = [
        make_feature_entry(f"Obj{i}", "Part::Box", f"obj{i}", f"Created obj{i}", i)
        for i in range(_MAX_ENTRIES + 10)
    ]
    out = format_feature_tree_context(tree)
    assert "omitted" in out
    assert "10 earlier" in out


def test_format_no_truncation_under_max():
    tree = [
        make_feature_entry(f"Obj{i}", "Part::Box", f"obj{i}", f"Created obj{i}", i)
        for i in range(_MAX_ENTRIES)
    ]
    out = format_feature_tree_context(tree)
    assert "omitted" not in out


def test_format_output_under_char_limit():
    tree = [
        make_feature_entry(f"Obj{i}", "Part::Feature", f"object_label_{i}", f"Created object {i}", i)
        for i in range(_MAX_ENTRIES)
    ]
    out = format_feature_tree_context(tree)
    assert len(out) <= _MAX_CHARS + 30  # small slack for truncation suffix


def test_format_skips_invalid_entries():
    valid = make_feature_entry("Box", "Part::Box", "box", "Created box", 1)
    invalid = make_feature_entry("OldBox", "Part::Box", "old_box", "Created old_box", 0)
    invalid["valid"] = False
    out = format_feature_tree_context([valid, invalid])
    assert "old_box" not in out
    assert "box" in out


def test_format_count_shows_valid_only():
    valid = make_feature_entry("Box", "Part::Box", "box", "Created box", 1)
    invalid = make_feature_entry("OldBox", "Part::Box", "old_box", "Created old_box", 0)
    invalid["valid"] = False
    out = format_feature_tree_context([valid, invalid])
    assert "1 object" in out
