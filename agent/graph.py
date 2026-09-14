"""
LangGraph StateGraph for the FreeCAD agent.

Graph topology:

  START → reason ──► [route] ──► run_tools ──────► post_tool ──► reason (loop)
                              ├─► confirm_and_run ─► post_tool ──► reason (loop)
                              ├─► halt ──► END  (step limit hit with tool calls pending)
                              └─► END

confirm_and_run pauses with interrupt(); callers see an "__interrupt__" stream
event and resume with Command(resume="yes" | "no").

post_tool diffs the FreeCAD document after every execute_script batch and
merges FeatureEntry dicts into state["feature_tree"].
"""

import os
import sqlite3
import threading
from functools import lru_cache
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent.config import UserConfig
from agent.history import steps_since_last_human, trim_history
from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT, format_feature_tree_context, format_tutorial_context
from agent.safety import confirmation_message, is_destructive
from agent.state import AgentState, make_feature_entry
from agent.tools import get_client, make_freecad_tools

CHECKPOINTS_PATH = Path(
    os.environ.get("CHECKPOINTS_DB") or Path(__file__).parent.parent / "checkpoints.db"
)
MAX_ITERATIONS = 20  # hard stop per user message to prevent infinite loops
TUTORIAL_CACHE_SIZE = 64

_checkpointer: SqliteSaver | None = None
_checkpointer_lock = threading.Lock()


def get_checkpointer() -> SqliteSaver:
    """Process-wide SqliteSaver, so every compiled graph shares one connection."""
    global _checkpointer
    with _checkpointer_lock:
        if _checkpointer is None:
            CHECKPOINTS_PATH.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(CHECKPOINTS_PATH), check_same_thread=False)
            _checkpointer = SqliteSaver(conn)
        return _checkpointer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _system_message(dynamic_context: str, cache_static_prompt: bool) -> SystemMessage:
    """
    Static prompt first, per-turn context after it.

    With Anthropic, the static block carries a cache breakpoint so the tool
    schemas + SYSTEM_PROMPT prefix is served from the prompt cache; the feature
    tree changes often, so it lives in a separate block after the breakpoint.
    """
    if not cache_static_prompt:
        return SystemMessage(content=f"{SYSTEM_PROMPT}\n\n{dynamic_context}")
    return SystemMessage(content=[
        {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}},
        {"type": "text", "text": dynamic_context},
    ])


def _latest_human_text(messages: list[BaseMessage]) -> str:
    for m in reversed(messages):
        if isinstance(m, HumanMessage):
            if isinstance(m.content, str):
                return m.content
            return " ".join(
                block.get("text", "") if isinstance(block, dict) else str(block)
                for block in m.content
            )
    return ""


def _current_tool_batch(messages: list[BaseMessage]) -> list[BaseMessage]:
    """Messages produced after the most recent AIMessage (its tool results)."""
    for i in range(len(messages) - 1, -1, -1):
        if isinstance(messages[i], AIMessage):
            return messages[i + 1:]
    return []


def _skipped_tool_results(tool_calls: list[dict], reason: str) -> list[ToolMessage]:
    """Answer tool calls that won't run, so the history stays valid for the provider."""
    return [
        ToolMessage(content=reason, tool_call_id=tc["id"], name=tc["name"])
        for tc in tool_calls
    ]


def _with_screenshot(result: dict) -> dict:
    """Copy the newest get_screenshot artifact (base64 PNG) into last_screenshot."""
    screenshot = None
    for msg in result.get("messages", []):
        if isinstance(msg, ToolMessage) and msg.name == "get_screenshot" and msg.artifact:
            screenshot = msg.artifact
    return {**result, "last_screenshot": screenshot} if screenshot else result


# ---------------------------------------------------------------------------
# Graph
# ---------------------------------------------------------------------------

def build_graph(config: UserConfig, rag_tool=None, tutorial_retriever=None, checkpointer=None):
    """
    Build and compile the agent graph for the given user config.

    Args:
        config:             user's LLM provider / model / API key config
        rag_tool:           optional LangChain @tool for RAG search (added when ChromaDB is ready)
        tutorial_retriever: optional retriever whose results are injected into the system prompt
        checkpointer:       defaults to the shared SQLite checkpointer
    """
    freecad_tools = make_freecad_tools(config)
    all_tools = freecad_tools + ([rag_tool] if rag_tool else [])

    llm = get_llm(config).bind_tools(all_tools)
    tool_node = ToolNode(all_tools)
    cache_static_prompt = config.provider == "anthropic"

    @lru_cache(maxsize=TUTORIAL_CACHE_SIZE)
    def tutorial_context_for(query: str) -> str:
        # The query is the latest user message, which stays the same for every
        # reason step of a turn — retrieve once, not once per step.
        return format_tutorial_context(tutorial_retriever.invoke(query))

    # -----------------------------------------------------------------------
    # Nodes
    # -----------------------------------------------------------------------

    def reason(state: AgentState) -> dict:
        """Ask the LLM what to do next, injecting feature tree and optional tutorial context."""
        history = [m for m in state["messages"] if not isinstance(m, SystemMessage)]

        context_parts = []
        if tutorial_retriever is not None:
            query = _latest_human_text(history)
            if query:
                try:
                    context_parts.append(tutorial_context_for(query))
                except Exception:
                    pass  # retrieval failure is non-fatal
        context_parts.append(format_feature_tree_context(state.get("feature_tree") or []))
        dynamic_context = "\n\n".join(part for part in context_parts if part)

        messages = [_system_message(dynamic_context, cache_static_prompt)] + trim_history(history)
        response = llm.invoke(messages)
        return {
            "messages": [response],
            "iteration": steps_since_last_human(history) + 1,
            "turn_index": state.get("turn_index", 0) + 1,
        }

    def run_tools(state: AgentState) -> dict:
        """Execute safe tool calls and capture screenshots into state."""
        return _with_screenshot(tool_node.invoke(state))

    def confirm_and_run(state: AgentState) -> dict:
        """
        For destructive tool calls: pause via interrupt() until the caller resumes
        with Command(resume=<answer>), then run or cancel all pending tool calls.
        The node re-runs from the top on resume, so nothing before interrupt()
        may have side effects.
        """
        tool_calls = state["messages"][-1].tool_calls

        # Find the first destructive call to build the confirmation prompt
        destructive_tc = next(
            tc for tc in tool_calls if is_destructive(tc["name"], tc["args"])
        )
        prompt = confirmation_message(destructive_tc["name"], destructive_tc["args"])

        user_response = interrupt({"question": prompt})

        if str(user_response).strip().lower() in ("yes", "y"):
            return _with_screenshot(tool_node.invoke(state))
        return {"messages": _skipped_tool_results(tool_calls, "Action cancelled by user.")}

    def halt(state: AgentState) -> dict:
        """Step limit reached: answer the pending tool calls and tell the user."""
        tool_calls = state["messages"][-1].tool_calls
        skipped = _skipped_tool_results(
            tool_calls, f"Not executed: step limit ({MAX_ITERATIONS}) reached."
        )
        notice = AIMessage(
            content=f"I stopped after {MAX_ITERATIONS} steps without finishing. "
                    "Tell me how you'd like to continue."
        )
        return {"messages": [*skipped, notice]}

    def post_tool(state: AgentState) -> dict:
        """
        Runs after every tool call batch.
        If the batch ran execute_script, diffs the FreeCAD document against the
        feature tree: new or re-created objects get fresh entries, and entries
        for deleted objects are marked invalid.
        """
        batch = _current_tool_batch(state.get("messages", []))
        had_execute = any(
            isinstance(m, ToolMessage) and m.name == "execute_script" for m in batch
        )
        if not had_execute:
            return {}

        try:
            current_objects = get_client(config).list_objects()
        except Exception:
            return {}

        feature_tree: list[dict] = state.get("feature_tree") or []
        valid_names = {e["name"] for e in feature_tree if e.get("valid", True)}
        current_names = {o["name"] for o in current_objects}
        turn = state.get("turn_index", 0)

        created = [
            make_feature_entry(
                name=o["name"],
                type_id=o["type"],
                label=o["label"],
                operation_summary=f"Created {o['label']} [{o['type']}]",
                turn_index=turn,
            )
            for o in current_objects
            if o["name"] not in valid_names
        ]
        deleted = [
            {**e, "valid": False}
            for e in feature_tree
            if e.get("valid", True) and e["name"] not in current_names
        ]

        updates = created + deleted
        return {"feature_tree": updates} if updates else {}

    # -----------------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------------

    def route_after_reason(state: AgentState) -> str:
        tool_calls = getattr(state["messages"][-1], "tool_calls", None)

        if not tool_calls:
            return END

        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return "halt"

        if any(is_destructive(tc["name"], tc["args"]) for tc in tool_calls):
            return "confirm_and_run"

        return "run_tools"

    # -----------------------------------------------------------------------
    # Graph assembly
    # -----------------------------------------------------------------------

    g = StateGraph(AgentState)
    g.add_node("reason", reason)
    g.add_node("run_tools", run_tools)
    g.add_node("confirm_and_run", confirm_and_run)
    g.add_node("halt", halt)
    g.add_node("post_tool", post_tool)

    g.add_edge(START, "reason")
    g.add_conditional_edges(
        "reason",
        route_after_reason,
        {"run_tools": "run_tools", "confirm_and_run": "confirm_and_run", "halt": "halt", END: END},
    )
    g.add_edge("run_tools", "post_tool")
    g.add_edge("confirm_and_run", "post_tool")
    g.add_edge("post_tool", "reason")
    g.add_edge("halt", END)

    return g.compile(checkpointer=checkpointer or get_checkpointer())
