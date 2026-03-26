"""
LangGraph StateGraph for the FreeCAD agent.

Graph topology:

  START → reason ──► [route] ──► run_tools ──► reason (loop)
                              ├─► confirm_and_run ──► reason (loop)
                              └─► END
"""

from pathlib import Path
from typing import Annotated

from langchain_core.messages import BaseMessage, SystemMessage
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from langgraph.types import interrupt
from typing_extensions import TypedDict

from agent.config import UserConfig
from agent.llm import get_llm
from agent.prompts import SYSTEM_PROMPT
from agent.safety import confirmation_message, is_destructive
from agent.tools import make_freecad_tools

CHECKPOINTS_PATH = Path(__file__).parent.parent / "checkpoints.db"
MAX_ITERATIONS = 20  # hard stop to prevent infinite loops


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    # Last screenshot (base64 PNG) — updated whenever get_screenshot runs
    last_screenshot: str | None
    # Counts total tool-call rounds this turn to enforce MAX_ITERATIONS
    iteration: int


# ---------------------------------------------------------------------------
# Node factories (need config + tools at runtime)
# ---------------------------------------------------------------------------

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
        """Ask the LLM what to do next."""
        messages = state["messages"]
        # Prepend system prompt if not already present
        if not messages or not isinstance(messages[0], SystemMessage):
            messages = [SystemMessage(content=SYSTEM_PROMPT)] + list(messages)
        response = llm.invoke(messages)
        return {
            "messages": [response],
            "iteration": state.get("iteration", 0) + 1,
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
        from langchain_core.messages import AIMessage, ToolMessage

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
            # Run all pending tool calls (safe + destructive)
            result = tool_node.invoke(state)
            screenshot = state.get("last_screenshot")
            for msg in result.get("messages", []):
                if getattr(msg, "name", None) == "get_screenshot":
                    content = msg.content
                    if content and not content.startswith(("CONNECTION ERROR", "FREECAD ERROR")):
                        screenshot = content
            return {**result, "last_screenshot": screenshot}
        else:
            # Cancel — inject ToolMessages telling the LLM the action was cancelled
            cancel_msgs = [
                ToolMessage(content="Action cancelled by user.", tool_call_id=tc["id"])
                for tc in tool_calls
            ]
            return {"messages": cancel_msgs}

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

    g.add_edge(START, "reason")
    g.add_conditional_edges(
        "reason",
        route_after_reason,
        {"run_tools": "run_tools", "confirm_and_run": "confirm_and_run", END: END},
    )
    g.add_edge("run_tools", "reason")
    g.add_edge("confirm_and_run", "reason")

    checkpointer = SqliteSaver.from_conn_string(str(CHECKPOINTS_PATH))
    return g.compile(checkpointer=checkpointer, interrupt_before=["confirm_and_run"])
