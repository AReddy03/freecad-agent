"""
Streamlit UI tests: drive ui/app.py headlessly with AppTest, using the same
fake LLM and fake FreeCAD as tests/test_graph.py (no API keys, no FreeCAD).
"""

import io
import json
from pathlib import Path

import pytest
import streamlit as st
from langchain_core.messages import AIMessage
from langgraph.checkpoint.memory import InMemorySaver
from PIL import Image
from streamlit.testing.v1 import AppTest

import agent.config as config_module
import agent.graph as graph_module
import agent.llm as llm_module
import agent.memory as memory_module
import agent.rag as rag_module
import agent.tools as tools_module
import agent.tutorial_rag as tutorial_rag_module
from agent.memory import MemoryStore
from tests.test_graph import FakeFreeCAD, ScriptedLLM, ai_tool

APP_PATH = str(Path(__file__).parent.parent / "ui" / "app.py")


def _png_b64() -> str:
    import base64
    buf = io.BytesIO()
    Image.new("RGB", (4, 4), "gray").save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()


@pytest.fixture
def app(monkeypatch, tmp_path):
    """Return start(replies) -> (AppTest, FakeFreeCAD) with every external service faked."""
    config_path = tmp_path / "config.json"
    config_path.write_text(json.dumps({"provider": "openai", "model": "gpt-4o", "api_key": "test"}))
    monkeypatch.setattr(config_module, "CONFIG_PATH", config_path)
    monkeypatch.delenv("FREECAD_HOST", raising=False)
    monkeypatch.delenv("FREECAD_PORT", raising=False)

    fake = FakeFreeCAD()
    monkeypatch.setattr(tools_module, "get_client", lambda config: fake)
    monkeypatch.setattr(graph_module, "get_client", lambda config: fake)
    monkeypatch.setattr(graph_module, "get_checkpointer", lambda: InMemorySaver())
    monkeypatch.setattr(rag_module, "collection_size", lambda: 0)
    monkeypatch.setattr(tutorial_rag_module, "collection_size", lambda: 0)
    monkeypatch.setattr(llm_module, "get_ollama_models", lambda: None)
    # Keep the app away from the real ~/.freecad-agent/memory.db
    memory_store = MemoryStore(db_path=tmp_path / "memory.db")
    monkeypatch.setattr(memory_module, "get_memory_store", lambda *args, **kwargs: memory_store)

    st.cache_data.clear()
    st.cache_resource.clear()

    def start(replies):
        monkeypatch.setattr(graph_module, "get_llm", lambda config: ScriptedLLM(messages=iter(replies)))
        at = AppTest.from_file(APP_PATH, default_timeout=60)
        at.run()
        assert not at.exception
        return at, fake

    yield start
    st.cache_resource.clear()


def _button(at: AppTest, label: str):
    return next(b for b in at.button if b.label == label)


def test_confirmation_flow_runs_the_destructive_tool(app):
    at, freecad = app([ai_tool("clear_document"), AIMessage("Document is now empty.")])
    freecad.objects["Box"] = "Part::Box"

    at.chat_input[0].set_value("clear everything").run()
    assert not at.exception
    assert at.session_state.pending_confirmation is True
    assert freecad.cleared == 0

    _button(at, "Yes, proceed").click().run()
    assert not at.exception
    assert freecad.cleared == 1
    assert at.session_state.pending_confirmation is False
    assert at.session_state.messages[-1]["content"] == "Document is now empty."


def test_declining_confirmation_leaves_document_alone(app):
    at, freecad = app([ai_tool("clear_document"), AIMessage("Okay, nothing removed.")])

    at.chat_input[0].set_value("clear everything").run()
    _button(at, "No, cancel").click().run()

    assert not at.exception
    assert freecad.cleared == 0
    assert at.session_state.messages[-1]["content"] == "Okay, nothing removed."


def test_screenshot_is_stored_once_as_bytes(app, monkeypatch):
    png_b64 = _png_b64()
    monkeypatch.setattr(FakeFreeCAD, "get_screenshot_base64", lambda self, direction="iso": png_b64)
    at, _ = app([ai_tool("get_screenshot"), AIMessage("Here it is.")])

    at.chat_input[0].set_value("show me").run()

    assert not at.exception
    last = at.session_state.messages[-1]
    assert isinstance(last["screenshot"], bytes)
    assert at.session_state.last_screenshot == last["screenshot"]
