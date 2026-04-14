"""
Agent state definitions.

Extracted from graph.py to avoid circular imports between graph.py and tools.py.
"""

from datetime import datetime, timezone
from typing import Annotated

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages
from typing_extensions import TypedDict


# ---------------------------------------------------------------------------
# Feature entry
# ---------------------------------------------------------------------------

def make_feature_entry(
    name: str,
    type_id: str,
    label: str,
    operation_summary: str,
    turn_index: int,
) -> dict:
    """Return a JSON-serializable dict representing one FreeCAD object."""
    return {
        "name": name,
        "type_id": type_id,
        "label": label,
        "operation_summary": operation_summary,
        "turn_index": turn_index,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "valid": True,
    }


# ---------------------------------------------------------------------------
# Reducer
# ---------------------------------------------------------------------------

def append_features(existing: list, new: list) -> list:
    """LangGraph reducer — feature_tree is append-only."""
    return existing + new


# ---------------------------------------------------------------------------
# Agent state
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages:        Annotated[list[BaseMessage], add_messages]
    last_screenshot: str | None
    iteration:       int
    feature_tree:    Annotated[list[dict], append_features]
    turn_index:      int
    # Pre-formatted strings injected into the system prompt each turn.
    # Computed live in the reason node closure; not serialized as Python objects.
    memory_context:  str | None
    skills_context:  str | None
