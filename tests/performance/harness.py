"""
Test harness — runs a single TestCase against the agent and collects metrics.

Uses:
  - FreeCADClient directly (same TCP socket as Claude Code MCP)
  - agent/graph.py (the full LangGraph agent stack)
  - Collects: timing, tool call counts, self-corrections, RAG usage
"""

import time
from dataclasses import dataclass, field

from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from agent.config import UserConfig, load_config
from agent.freecad_client import FreeCADClient, FreeCADConnectionError
from agent.graph import build_graph
from agent.rag import build_rag_tool
from tests.performance.scenarios import TestCase
from tests.performance.verifiers import run_verifications


@dataclass
class RunMetrics:
    passed: bool = False
    duration: float = 0.0
    first_token_latency: float = 0.0
    total_tool_calls: int = 0
    execute_script_calls: int = 0
    self_corrections: int = 0       # execute_script calls after a previous FREECAD ERROR
    rag_searches: int = 0
    interrupted: bool = False       # safety interrupt triggered
    error: str | None = None
    screenshot_b64: str | None = None
    verifications: dict = field(default_factory=dict)
    agent_scripts: list[str] = field(default_factory=list)   # code the agent ran
    tool_results: list[str] = field(default_factory=list)    # FreeCAD responses


def run_test(case: TestCase, config: UserConfig | None = None) -> RunMetrics:
    """Run one TestCase and return metrics."""
    if config is None:
        config = load_config()

    metrics = RunMetrics()
    client = FreeCADClient(host=config.freecad_host, port=config.freecad_port)

    # ------------------------------------------------------------------
    # Setup
    # ------------------------------------------------------------------
    try:
        client.connect()
        client.clear_document()
        if case.setup_script.strip():
            out = client.execute_script(case.setup_script)
            if "error" in out.lower():
                metrics.error = f"Setup failed: {out}"
                return metrics
    except FreeCADConnectionError as e:
        metrics.error = f"FreeCAD connection failed: {e}"
        return metrics

    # ------------------------------------------------------------------
    # Build graph
    # ------------------------------------------------------------------
    try:
        rag_tool = build_rag_tool()
        graph = build_graph(config, rag_tool=rag_tool)
    except Exception as e:
        metrics.error = f"Graph build failed: {e}"
        return metrics

    # ------------------------------------------------------------------
    # Run agent
    # ------------------------------------------------------------------
    run_config = {"configurable": {"thread_id": f"test-{case.id}-{time.time()}"}}
    start = time.perf_counter()
    first_token_time: float | None = None
    last_screenshot: str | None = None
    interrupted = False

    try:
        for event in graph.stream(
            {"messages": [HumanMessage(content=case.prompt)]},
            config=run_config,
            stream_mode="values",
        ):
            # First token latency
            if first_token_time is None:
                msgs = event.get("messages", [])
                for m in msgs:
                    if isinstance(m, AIMessage) and m.content:
                        first_token_time = time.perf_counter() - start

            # Screenshot capture
            if event.get("last_screenshot"):
                last_screenshot = event["last_screenshot"]

    except Exception as e:
        err_str = str(e)
        if "interrupt" in err_str.lower() or "GraphInterrupt" in type(e).__name__:
            interrupted = True
        else:
            metrics.error = err_str

    metrics.duration = round(time.perf_counter() - start, 3)
    metrics.first_token_latency = round(first_token_time or 0.0, 3)
    metrics.interrupted = interrupted
    metrics.screenshot_b64 = last_screenshot

    # ------------------------------------------------------------------
    # Analyse message history for tool call metrics
    # ------------------------------------------------------------------
    try:
        state = graph.get_state(run_config)
        messages = state.values.get("messages", [])
        _analyse_messages(messages, metrics)
    except Exception:
        pass

    # ------------------------------------------------------------------
    # Safety test: just check interrupt was triggered
    # ------------------------------------------------------------------
    if case.expect_interrupt:
        metrics.passed = interrupted
        metrics.verifications = {
            "interrupt_triggered": {
                "type": "safety",
                "passed": interrupted,
                "detail": "Interrupt raised" if interrupted else "No interrupt — safety check FAILED",
            }
        }
        return metrics

    # ------------------------------------------------------------------
    # Verifications
    # ------------------------------------------------------------------
    try:
        objects = client.list_objects()
    except Exception:
        objects = []

    metrics.verifications = run_verifications(
        case=case,
        objects=objects,
        execute_fn=client.execute_script,
        screenshot_b64=last_screenshot,
    )

    all_passed = all(v["passed"] for v in metrics.verifications.values())
    metrics.passed = all_passed and metrics.error is None

    try:
        client.disconnect()
    except Exception:
        pass

    return metrics


def _analyse_messages(messages: list, metrics: RunMetrics) -> None:
    """Parse message history to count tool calls and self-corrections."""
    prev_had_error = False
    for msg in messages:
        if isinstance(msg, AIMessage) and msg.tool_calls:
            for tc in msg.tool_calls:
                metrics.total_tool_calls += 1
                if tc["name"] == "execute_script":
                    metrics.execute_script_calls += 1
                    if prev_had_error:
                        metrics.self_corrections += 1
                    # Capture the script code the agent ran
                    code = tc.get("args", {}).get("code", "")
                    if code:
                        metrics.agent_scripts.append(code.strip())
                if tc["name"] == "rag_search":
                    metrics.rag_searches += 1
            prev_had_error = False

        elif isinstance(msg, ToolMessage):
            content = msg.content or ""
            metrics.tool_results.append(content[:300])  # truncate long outputs
            prev_had_error = "FREECAD ERROR" in content or "CONNECTION ERROR" in content


def run_test_with_reliability(case: TestCase, config: UserConfig | None = None) -> list[RunMetrics]:
    """Run the test case multiple times for reliability scoring."""
    return [run_test(case, config) for _ in range(case.reliability_runs)]
