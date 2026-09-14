"""
Offline tests for agent/graph.py.

A scripted fake LLM and an in-memory fake FreeCAD stand in for the real
services, so these run without API keys or a FreeCAD instance.
"""

import base64
import itertools
from pathlib import Path

import pytest
from langchain_core.documents import Document
from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from pydantic import Field

import agent.graph as graph_module
import agent.tools as tools_module
from agent.config import UserConfig
from agent.memory import MemoryStore, MemoryType
from agent.prompts import SYSTEM_PROMPT
from agent.skills import Skill

SCREENSHOT_B64 = base64.b64encode(b"\x89PNG" + b"x" * 5000).decode()
_call_ids = itertools.count()


# ---------------------------------------------------------------------------
# Fakes
# ---------------------------------------------------------------------------

class ScriptedLLM(GenericFakeChatModel):
    """Replies with pre-scripted AIMessages and records every prompt it receives."""

    prompts: list = Field(default_factory=list)

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.prompts.append(list(messages))
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


class FakeFreeCAD:
    """In-memory document that understands scripts like 'add Box' / 'del Box'."""

    def __init__(self):
        self.objects: dict[str, str] = {}
        self.list_calls = 0
        self.cleared = 0

    def execute_script(self, code: str) -> str:
        op, name = code.split()
        if op == "add":
            self.objects[name] = "Part::Box"
        else:
            self.objects.pop(name, None)
        return ""

    def list_objects(self) -> list[dict]:
        self.list_calls += 1
        return [{"name": n, "label": n.lower(), "type": t} for n, t in self.objects.items()]

    def get_screenshot_base64(self, direction: str = "iso") -> str:
        return SCREENSHOT_B64

    def clear_document(self) -> None:
        self.objects.clear()
        self.cleared += 1

    def save_document(self, path: str = "") -> str:
        return path


class CountingRetriever:
    def __init__(self):
        self.calls = 0

    def invoke(self, query: str) -> list[Document]:
        self.calls += 1
        return [Document(page_content="Pad the sketch.", metadata={"title": "Pads"})]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def freecad(monkeypatch):
    fake = FakeFreeCAD()
    monkeypatch.setattr(tools_module, "get_client", lambda config: fake)
    monkeypatch.setattr(graph_module, "get_client", lambda config: fake)
    return fake


def ai_tool(name: str, **args) -> AIMessage:
    return AIMessage(content="", tool_calls=[{"name": name, "args": args, "id": f"call_{next(_call_ids)}"}])


def make_graph(monkeypatch, replies, provider="openai", **kwargs):
    llm = ScriptedLLM(messages=iter(replies))
    monkeypatch.setattr(graph_module, "get_llm", lambda config: llm)
    config = UserConfig(provider=provider, model="test", api_key="test")
    graph = graph_module.build_graph(config, checkpointer=InMemorySaver(), **kwargs)
    return graph, llm


def thread(name: str = "t") -> dict:
    return {"configurable": {"thread_id": name}}


def ask(graph, text: str, cfg: dict) -> dict:
    return graph.invoke({"messages": [HumanMessage(text)]}, cfg)


def assert_tool_calls_answered(messages) -> None:
    answered = {m.tool_call_id for m in messages if isinstance(m, ToolMessage)}
    for m in messages:
        if isinstance(m, AIMessage):
            for tc in m.tool_calls:
                assert tc["id"] in answered, f"tool call {tc['name']} has no result"


# ---------------------------------------------------------------------------
# Screenshots
# ---------------------------------------------------------------------------

def test_screenshot_reaches_state_but_not_the_llm(monkeypatch, freecad):
    graph, llm = make_graph(monkeypatch, [ai_tool("get_screenshot"), AIMessage("done")])
    state = ask(graph, "show me", thread())

    assert state["last_screenshot"] == SCREENSHOT_B64
    tool_msg = next(m for m in state["messages"] if isinstance(m, ToolMessage))
    assert SCREENSHOT_B64 not in str(tool_msg.content)
    assert all(SCREENSHOT_B64 not in str(m.content) for m in llm.prompts[1])


# ---------------------------------------------------------------------------
# Confirmation flow
# ---------------------------------------------------------------------------

def test_destructive_call_pauses_until_confirmed(monkeypatch, freecad):
    freecad.objects["Box"] = "Part::Box"
    graph, _ = make_graph(monkeypatch, [ai_tool("clear_document"), AIMessage("cleared")])
    cfg = thread()

    events = list(graph.stream({"messages": [HumanMessage("clear it")]}, cfg, stream_mode="updates"))
    interrupts = [e["__interrupt__"] for e in events if "__interrupt__" in e]
    assert interrupts, "stream should surface the confirmation as an __interrupt__ event"
    assert "all objects" in interrupts[0][0].value["question"]
    assert freecad.cleared == 0
    assert graph.get_state(cfg).next == ("confirm_and_run",)

    state = graph.invoke(Command(resume="yes"), cfg)
    assert freecad.cleared == 1
    assert state["messages"][-1].content == "cleared"
    assert_tool_calls_answered(state["messages"])


def test_declined_confirmation_answers_every_tool_call(monkeypatch, freecad):
    graph, _ = make_graph(monkeypatch, [ai_tool("clear_document"), AIMessage("left it alone")])
    cfg = thread()

    ask(graph, "clear it", cfg)  # pauses at the confirmation
    state = graph.invoke(Command(resume="no"), cfg)

    assert freecad.cleared == 0
    assert any(
        isinstance(m, ToolMessage) and m.content == "Action cancelled by user."
        for m in state["messages"]
    )
    assert state["messages"][-1].content == "left it alone"
    assert_tool_calls_answered(state["messages"])


# ---------------------------------------------------------------------------
# Step limit
# ---------------------------------------------------------------------------

def test_step_limit_halts_cleanly_and_resets_per_message(monkeypatch, freecad):
    monkeypatch.setattr(graph_module, "MAX_ITERATIONS", 2)
    graph, _ = make_graph(monkeypatch, [
        ai_tool("list_objects"), ai_tool("list_objects"),  # turn 1: 2nd step hits the limit
        ai_tool("list_objects"), AIMessage("all good"),    # turn 2: fresh budget
    ])
    cfg = thread()

    state = ask(graph, "loop forever", cfg)
    assert "stopped after 2 steps" in state["messages"][-1].content
    assert_tool_calls_answered(state["messages"])

    state = ask(graph, "try again", cfg)
    assert state["messages"][-1].content == "all good"
    assert state["iteration"] == 2


# ---------------------------------------------------------------------------
# Feature tree
# ---------------------------------------------------------------------------

def test_feature_tree_tracks_deletes_and_recreation(monkeypatch, freecad):
    graph, _ = make_graph(monkeypatch, [
        ai_tool("execute_script", code="add Box"),
        ai_tool("execute_script", code="add Cyl"),
        ai_tool("execute_script", code="del Box"),
        AIMessage("done"),
        ai_tool("execute_script", code="add Box"),
        AIMessage("done again"),
    ])
    cfg = thread()

    state = ask(graph, "build", cfg)
    assert {e["name"]: e["valid"] for e in state["feature_tree"]} == {"Box": False, "Cyl": True}

    state = ask(graph, "bring the box back", cfg)
    assert {e["name"]: e["valid"] for e in state["feature_tree"]} == {"Box": True, "Cyl": True}
    assert len(state["feature_tree"]) == 2


def test_post_tool_only_lists_objects_after_execute_script(monkeypatch, freecad):
    graph, _ = make_graph(monkeypatch, [
        ai_tool("execute_script", code="add Box"),
        ai_tool("get_screenshot"),
        AIMessage("done"),
    ])
    ask(graph, "build", thread())
    assert freecad.list_calls == 1


# ---------------------------------------------------------------------------
# Prompt construction
# ---------------------------------------------------------------------------

def test_tutorial_retrieval_runs_once_per_user_message(monkeypatch, freecad):
    retriever = CountingRetriever()
    graph, llm = make_graph(
        monkeypatch,
        [ai_tool("list_objects"), ai_tool("list_objects"), AIMessage("done")],
        tutorial_retriever=retriever,
    )
    ask(graph, "make a pad", thread())

    assert len(llm.prompts) == 3
    assert retriever.calls == 1
    assert all("Pad the sketch." in str(prompt[0].content) for prompt in llm.prompts)


def test_anthropic_system_prompt_has_cache_breakpoint(monkeypatch, freecad):
    graph, llm = make_graph(monkeypatch, [AIMessage("hi")], provider="anthropic")
    ask(graph, "hello", thread())

    static, dynamic = llm.prompts[0][0].content
    assert static == {"type": "text", "text": SYSTEM_PROMPT, "cache_control": {"type": "ephemeral"}}
    assert "Current document state" in dynamic["text"]


class FakeSkills:
    def __init__(self):
        self.match_calls = 0

    def list_all(self) -> list[dict]:
        return [{"name": "sketching", "description": "Sketch constraints guidance. Details."}]

    def match_skills(self, query: str, top_k: int = 2) -> list[Skill]:
        self.match_calls += 1
        return [Skill(name="sketching", description="", content="Fully constrain every sketch.", path=Path("SKILL.md"))]

    def skill_names(self) -> list[str]:
        return ["sketching"]


def test_skills_index_is_static_and_matched_skills_are_computed_once(monkeypatch, freecad):
    skills = FakeSkills()
    graph, llm = make_graph(
        monkeypatch,
        [ai_tool("list_objects"), ai_tool("list_objects"), AIMessage("done")],
        provider="anthropic",
        skills_registry=skills,
    )
    ask(graph, "sketch a bracket", thread())

    static, dynamic = llm.prompts[0][0].content
    assert static["text"].startswith(SYSTEM_PROMPT)
    assert "`sketching`" in static["text"]          # index sits in the cached block
    assert "Fully constrain every sketch." in dynamic["text"]
    assert skills.match_calls == 1                  # 3 reason steps, 1 match


def test_memory_is_injected_and_session_summary_saved(monkeypatch, freecad, tmp_path):
    store = MemoryStore(db_path=tmp_path / "memory.db")
    store.save("User prefers millimetres", MemoryType.PREFERENCE)
    monkeypatch.setattr(graph_module, "_saved_summary_turns", set())
    graph, llm = make_graph(
        monkeypatch,
        [ai_tool("execute_script", code="add Box"), AIMessage("Built a box.")],
        memory_store=store,
    )
    ask(graph, "build a box", thread())

    assert "User prefers millimetres" in llm.prompts[0][0].content
    summaries = store.get_session_summaries()
    assert len(summaries) == 1
    assert "build a box" in summaries[0]["content"]


def test_other_providers_get_plain_system_prompt(monkeypatch, freecad):
    graph, llm = make_graph(monkeypatch, [AIMessage("hi")], provider="openai")
    ask(graph, "hello", thread())

    content = llm.prompts[0][0].content
    assert isinstance(content, str)
    assert content.startswith(SYSTEM_PROMPT)
    assert "Current document state" in content
