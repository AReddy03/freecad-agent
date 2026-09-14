"""Unit tests for agent/history.py."""

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.history import steps_since_last_human, trim_history


def turn(i: int, output_size: int) -> list:
    """One user turn: request → tool call → tool result → answer."""
    return [
        HumanMessage(f"request {i}"),
        AIMessage(content="", tool_calls=[{"name": "execute_script", "args": {"code": "x"}, "id": f"c{i}"}]),
        ToolMessage(content="o" * output_size, tool_call_id=f"c{i}", name="execute_script"),
        AIMessage(f"done {i}"),
    ]


def test_trim_keeps_everything_under_budget():
    msgs = turn(0, 10) + turn(1, 10)
    assert trim_history(msgs, max_chars=10_000) == msgs


def test_trim_drops_oldest_whole_turns():
    msgs = turn(0, 500) + turn(1, 500) + turn(2, 500)  # ~528 chars per turn
    assert trim_history(msgs, max_chars=1200) == msgs[4:]


def test_trim_always_keeps_latest_turn():
    msgs = turn(0, 10) + turn(1, 5000)
    assert trim_history(msgs, max_chars=100) == msgs[4:]


def test_trimmed_history_never_splits_a_tool_call_from_its_result():
    msgs = turn(0, 300) + turn(1, 300) + turn(2, 300)
    for budget in range(0, 2000, 50):
        trimmed = trim_history(msgs, max_chars=budget)
        assert isinstance(trimmed[0], HumanMessage)
        answered = {m.tool_call_id for m in trimmed if isinstance(m, ToolMessage)}
        called = {tc["id"] for m in trimmed if isinstance(m, AIMessage) for tc in m.tool_calls}
        assert called == answered


def test_steps_since_last_human():
    assert steps_since_last_human([]) == 0
    assert steps_since_last_human(turn(0, 1)) == 2
    assert steps_since_last_human(turn(0, 1) + [HumanMessage("again"), AIMessage("a")]) == 1
