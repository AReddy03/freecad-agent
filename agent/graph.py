"""
LangGraph StateGraph for the FreeCAD agent.

Graph topology:

  START → reason ──► [route] ──► run_tools ──► post_tool ──► reason (loop)
                              ├─► confirm_and_run ──► post_tool ──► reason (loop)
                              └─► END

post_tool diffs the FreeCAD document after every execute_script call and
appends new FeatureEntry dicts to state["feature_tree"].
"""

import sqlite3
from pathlib import Path

from langchain_core.messages import AIMessage, BaseMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt

from agent.config import UserConfig
from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT, format_feature_tree_context
from agent.safety import confirmation_message, is_destructive
from agent.state import AgentState, make_feature_entry
from agent.tools import _get_client, make_freecad_tools

CHECKPOINTS_PATH = Path(__file__).parent.parent / "checkpoints.db"
MAX_ITERATIONS = 20  # hard stop to prevent infinite loops


def build_graph(config: UserConfig, rag_tool=None):
    """
    Build and compile the agent graph for the given user config.
    Returns a compiled LangGraph graph with a SqliteSaver checkpointer.

    Args:
        config:   user's LLM provider / model / API key config
        rag_tool: optional LangChain @tool for RAG search (added when ChromaDB is ready)
    """
    freecad_tools = make_freecad_tools(config)
    all_tools = freecad_tools + ([rag_tool] if rag_tool else [])

    llm = get_llm(config).bind_tools(all_tools)
    tool_node = ToolNode(all_tools)

    # -----------------------------------------------------------------------
    # Nodes
    # -----------------------------------------------------------------------

    def reason(state: AgentState) -> dict:
        """Ask the LLM what to do next, injecting the feature tree into context."""
        feature_tree = state.get("feature_tree") or []
        tree_context = format_feature_tree_context(feature_tree)
        system_content = SYSTEM_PROMPT + "\n\n" + tree_context

        # Replace any existing SystemMessage; keep all other messages.
        messages = [
            m for m in state["messages"] if not isinstance(m, SystemMessage)
        ]
        messages = [SystemMessage(content=system_content)] + messages

        response = llm.invoke(messages)
        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
            "turn_index": state.get("turn_index", 0) + 1,
        }

    def run_tools(state: AgentState) -> dict:
        """Execute safe tool calls and capture screenshots into state."""
        result = tool_node.invoke(state)
        screenshot = state.get("last_screenshot")

        for msg in result.get("messages", []):
            if getattr(msg, "name", None) == "get_screenshot":
                content = msg.content
                if content and not content.startswith(("CONNECTION ERROR", "FREECAD ERROR")):
                    screenshot = content

        return {**result, "last_screenshot": screenshot}

    def confirm_and_run(state: AgentState) -> dict:
        """
        For destructive tool calls: pause via interrupt(), wait for user
        confirmation, then either run or cancel all pending tool calls.
        """
        last: AIMessage = state["messages"][-1]
        tool_calls = last.tool_calls

        # Find the first destructive call to build the confirmation prompt
        destructive_tc = next(
            tc for tc in tool_calls if is_destructive(tc["name"], tc["args"])
        )
        prompt = confirmation_message(destructive_tc["name"], destructive_tc["args"])

        # Pause here — control returns to the UI; resumes on next graph invocation
        user_response: str = interrupt({"question": prompt})

        if user_response.strip().lower() in ("yes", "y"):
            result = tool_node.invoke(state)
            screenshot = state.get("last_screenshot")
            for msg in result.get("messages", []):
                if getattr(msg, "name", None) == "get_screenshot":
                    content = msg.content
                    if content and not content.startswith(("CONNECTION ERROR", "FREECAD ERROR")):
                        screenshot = content
            return {**result, "last_screenshot": screenshot}
        else:
            cancel_msgs = [
                ToolMessage(content="Action cancelled by user.", tool_call_id=tc["id"])
                for tc in tool_calls
            ]
            return {"messages": cancel_msgs}

    def post_tool(state: AgentState) -> dict:
        """
        Runs after every tool call batch.
        Diffs FreeCAD document state against the feature tree and appends
        new FeatureEntry dicts for any objects that were created.
        Also marks entries as invalid if objects were deleted.
        """
        # Only inspect FreeCAD if execute_script was called in the last batch
        recent_messages: list[BaseMessage] = state.get("messages", [])[-20:]
        had_execute = any(
            isinstance(m, ToolMessage) and getattr(m, "name", "") == "execute_script"
            for m in recent_messages
        )
        if not had_execute:
            return {}

        try:
            client = _get_client(config)
            current_objects = client.list_objects()
        except Exception:
            return {}

        feature_tree: list[dict] = list(state.get("feature_tree") or [])
        known_names = {e["name"] for e in feature_tree}
        turn = state.get("turn_index", 0)

        # New objects → append entries
        new_entries = [
            make_feature_entry(
                name=o["name"],
                type_id=o["type"],
                label=o["label"],
                operation_summary=f"Created {o['label']} [{o['type']}]",
                turn_index=turn,
            )
            for o in current_objects
            if o["name"] not in known_names
        ]

        # Deleted objects → mark existing entries invalid (mutate in-place)
        current_names = {o["name"] for o in current_objects}
        for entry in feature_tree:
            if entry.get("valid", True) and entry["name"] not in current_names:
                entry["valid"] = False

        return {"feature_tree": new_entries} if new_entries else {}

    # -----------------------------------------------------------------------
    # Routing
    # -----------------------------------------------------------------------

    def route_after_reason(state: AgentState) -> str:
        last = state["messages"][-1]
        tool_calls = getattr(last, "tool_calls", None)

        if not tool_calls:
            return END

        if state.get("iteration", 0) >= MAX_ITERATIONS:
            return END

        for tc in tool_calls:
            if is_destructive(tc["name"], tc["args"]):
                return "confirm_and_run"

        return "run_tools"

    # -----------------------------------------------------------------------
    # Graph assembly
    # -----------------------------------------------------------------------

    g = StateGraph(AgentState)
    g.add_node("reason", reason)
    g.add_node("run_tools", run_tools)
    g.add_node("confirm_and_run", confirm_and_run)
    g.add_node("post_tool", post_tool)

    g.add_edge(START, "reason")
    g.add_conditional_edges(
        "reason",
        route_after_reason,
        {"run_tools": "run_tools", "confirm_and_run": "confirm_and_run", END: END},
    )
    g.add_edge("run_tools", "post_tool")
    g.add_edge("confirm_and_run", "post_tool")
    g.add_edge("post_tool", "reason")

    conn = sqlite3.connect(str(CHECKPOINTS_PATH), check_same_thread=False)
    checkpointer = SqliteSaver(conn)
    return g.compile(checkpointer=checkpointer, interrupt_before=["confirm_and_run"])
