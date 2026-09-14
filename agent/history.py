"""
Helpers for the message history the reason node sends to the LLM.

History is only ever cut at user-turn boundaries (a HumanMessage), so every
AIMessage tool call stays paired with its ToolMessage results — providers
reject a tool call whose result is missing.
"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

MAX_HISTORY_CHARS = 120_000  # ~30k tokens at 4 chars/token


def _size(message: BaseMessage) -> int:
    size = len(str(message.content))
    for tc in getattr(message, "tool_calls", None) or []:
        size += len(str(tc.get("args", "")))
    return size


def trim_history(
    messages: list[BaseMessage], max_chars: int = MAX_HISTORY_CHARS
) -> list[BaseMessage]:
    """
    Drop the oldest whole user turns until the history fits in max_chars.
    The latest turn is always kept, even if it alone exceeds the budget.
    """
    turn_starts = [i for i, m in enumerate(messages) if isinstance(m, HumanMessage)]
    total = sum(_size(m) for m in messages)
    cut = 0
    for next_start in turn_starts[1:]:
        if total <= max_chars:
            break
        total -= sum(_size(m) for m in messages[cut:next_start])
        cut = next_start
    return messages[cut:]


def steps_since_last_human(messages: list[BaseMessage]) -> int:
    """Number of LLM responses (AIMessages) since the most recent user message."""
    count = 0
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            break
        if isinstance(m, AIMessage):
            count += 1
    return count
