"""
FreeCAD Agent — Streamlit UI

Layout:
  Sidebar  — Settings (provider, model, API key, connection test)
  Main col — Chat window + streamed responses
  Right col — Live screenshot + object tree

Streamlit re-runs this whole script on every interaction, so anything slow
(graph construction, vector store counts, Ollama discovery) is cached.
"""

import base64
import sys
import uuid
from pathlib import Path

import streamlit as st

# Ensure project root is on the path when running via `streamlit run ui/app.py`
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent import rag, tutorial_rag
from agent.config import PROVIDER_MODELS, UserConfig, env_overridden_fields, load_config, save_config
from agent.freecad_client import FreeCADClient
from agent.llm import get_ollama_models
from agent.tools import get_client

# ---------------------------------------------------------------------------
# Page config
# ---------------------------------------------------------------------------

st.set_page_config(
    page_title="FreeCAD Agent",
    page_icon="⚙️",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Cached resources
# ---------------------------------------------------------------------------

@st.cache_data(ttl=10, show_spinner=False)
def _ollama_models() -> list[str] | None:
    return get_ollama_models()


@st.cache_data(ttl=60, show_spinner=False)
def _docs_count() -> int:
    return rag.collection_size()


@st.cache_data(ttl=60, show_spinner=False)
def _tutorials_count() -> int:
    return tutorial_rag.collection_size()


@st.cache_resource(max_entries=4, show_spinner="Starting agent…")
def _build_graph(config_json: str, docs_ready: bool, tutorials_ready: bool):
    """
    One compiled graph per distinct config, shared by every browser session.
    Conversation state lives in the checkpointer, keyed by thread_id, so a new
    session only needs a new thread_id — not a new graph.
    """
    from agent.graph import build_graph
    cfg = UserConfig.model_validate_json(config_json)
    rag_tool = rag.build_rag_tool() if docs_ready else None
    tutorial_retriever = tutorial_rag.build_tutorial_retriever() if tutorials_ready else None
    return build_graph(cfg, rag_tool=rag_tool, tutorial_retriever=tutorial_retriever)


# ---------------------------------------------------------------------------
# Session state defaults
# ---------------------------------------------------------------------------

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": str, "content": str, "screenshot": bytes|None}
if "last_screenshot" not in st.session_state:
    st.session_state.last_screenshot = None  # PNG bytes
if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = False  # True when graph is interrupted
if "objects" not in st.session_state:
    st.session_state.objects = None  # last object list read from FreeCAD

# ---------------------------------------------------------------------------
# Sidebar — Settings
# ---------------------------------------------------------------------------

config: UserConfig = load_config()
env_fields = env_overridden_fields()

with st.sidebar:
    st.title("⚙️ FreeCAD Agent")
    st.divider()

    st.subheader("LLM Settings")

    # Provider selector
    _providers = [p for p in PROVIDER_MODELS if p != "ollama"] + ["ollama"]
    provider = st.selectbox(
        "Provider",
        options=_providers,
        index=_providers.index(config.provider) if config.provider in _providers else 0,
        key="provider_select",
    )

    # Model selector — dynamic per provider
    if provider == "ollama":
        ollama_models = _ollama_models()
        if ollama_models is None:
            st.warning("Ollama not detected — is it running?")
            model_options = ["(ollama not running)"]
        else:
            st.success("Ollama detected")
            model_options = ollama_models or ["(no models pulled)"]
    else:
        model_options = PROVIDER_MODELS[provider]

    current_model = config.model if config.model in model_options else model_options[0]
    model = st.selectbox("Model", options=model_options, index=model_options.index(current_model))

    # API key (hidden for Ollama)
    api_key = config.api_key
    _placeholders = {
        "anthropic": "sk-ant-...",
        "openai":    "sk-...",
        "google":    "AIza...",
    }
    if provider != "ollama":
        api_key = st.text_input(
            "API Key",
            value=config.api_key,
            type="password",
            placeholder=_placeholders.get(provider, "Paste your API key here"),
        )

    # FreeCAD connection
    st.divider()
    st.subheader("FreeCAD Connection")
    freecad_host = st.text_input(
        "Host",
        value=config.freecad_host,
        disabled="freecad_host" in env_fields,
        help="Set by the FREECAD_HOST environment variable." if "freecad_host" in env_fields else None,
    )
    freecad_port = st.number_input(
        "Port",
        value=config.freecad_port,
        min_value=1,
        max_value=65535,
        disabled="freecad_port" in env_fields,
        help="Set by the FREECAD_PORT environment variable." if "freecad_port" in env_fields else None,
    )

    # Tutorial RAG toggle
    st.divider()
    st.subheader("Experimental")
    use_tutorial_rag = st.toggle(
        "Spatial reasoning (tutorial RAG)",
        value=config.use_tutorial_rag,
        help=(
            "Automatically injects relevant FreeCAD design tutorials into every agent turn "
            "to improve spatial reasoning. Requires running: python scripts/ingest_tutorials.py"
        ),
    )
    tutorials_count = _tutorials_count()
    if use_tutorial_rag and tutorials_count == 0:
        st.warning(
            "Tutorial corpus not indexed yet. Run:\n```\npython scripts/ingest_tutorials.py\n```"
        )

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Settings", use_container_width=True):
            config = UserConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                freecad_host=freecad_host,
                freecad_port=int(freecad_port),
                use_tutorial_rag=use_tutorial_rag,
            )
            save_config(config)
            # No explicit reset needed: the graph cache is keyed by config.
            st.success("Saved.")

    with col2:
        if st.button("Test Connection", use_container_width=True):
            _test_config = UserConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                freecad_host=freecad_host,
                freecad_port=int(freecad_port),
            )

            # Test FreeCAD (fresh client: host/port may not be saved yet)
            try:
                with FreeCADClient(host=freecad_host, port=int(freecad_port)):
                    pass
                st.success("FreeCAD: connected")
            except Exception as e:
                st.error(f"FreeCAD: {e}")

            # Test LLM
            if provider != "ollama" and not api_key:
                st.warning("LLM: no API key entered")
            else:
                try:
                    from agent.llm import get_llm
                    llm = get_llm(_test_config)
                    llm.invoke("Say OK")
                    st.success("LLM: connected")
                except Exception as e:
                    st.error(f"LLM: {e}")

    # RAG status
    st.divider()
    st.subheader("Knowledge Base")
    docs_count = _docs_count()
    if docs_count == 0:
        st.warning("API docs not indexed. Run:\n```\npython scripts/ingest.py\n```")
    else:
        st.success(f"API docs: {docs_count} chunks")
    if tutorials_count > 0:
        st.success(f"Tutorials: {tutorials_count} chunks")

    # Session controls
    st.divider()
    if st.button("New Session", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.last_screenshot = None
        st.session_state.pending_confirmation = False
        st.rerun()

    if st.button("Clear Document", use_container_width=True):
        try:
            get_client(config).clear_document()
            st.session_state.objects = []
            st.success("Document cleared.")
        except Exception as e:
            st.error(f"Could not clear document: {e}")
        # New thread forces a fresh feature_tree in graph state
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.last_screenshot = None
        st.session_state.pending_confirmation = False
        st.rerun()

# ---------------------------------------------------------------------------
# Graph access
# ---------------------------------------------------------------------------

def _get_graph():
    if not config.is_ready:
        return None
    return _build_graph(
        config.model_dump_json(),
        docs_ready=docs_count > 0,
        tutorials_ready=config.use_tutorial_rag and tutorials_count > 0,
    )


# ---------------------------------------------------------------------------
# Graph runner  (defined before layout so calls below can reference it)
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "execute_script":  "⚙️ Executing script",
    "get_screenshot":  "📸 Taking screenshot",
    "list_objects":    "🔍 Listing objects",
    "rag_search":      "📚 Searching docs",
    "clear_document":  "🗑️ Clearing document",
    "save_document":   "💾 Saving document",
}


def _interrupt_question(interrupts) -> str:
    """Pull the confirmation prompt out of an "__interrupt__" stream event."""
    for item in interrupts or ():
        value = getattr(item, "value", None)
        if isinstance(value, dict) and value.get("question"):
            return value["question"]
        if isinstance(value, str):
            return value
    return "Confirm this action?"


def _run_graph(user_input: str, *, resume: bool = False):
    """
    Stream one graph run and update session state.
    resume=True answers a pending confirmation instead of sending a new message.
    """
    from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
    from langgraph.types import Command

    graph = _get_graph()
    if not graph:
        st.error("Agent not ready — check settings.")
        return

    # Add user message to display
    st.session_state.messages.append({"role": "user", "content": user_input})

    run_config = {"configurable": {"thread_id": st.session_state.thread_id}}
    if resume:
        payload = Command(resume=user_input)
    else:
        payload = {"messages": [HumanMessage(content=user_input)]}

    assistant_text = ""
    new_screenshot: bytes | None = None
    question: str | None = None

    with st.chat_message("assistant"):
        text_placeholder = st.empty()

        with st.status("Agent running…", expanded=True) as agent_status:
            try:
                for event in graph.stream(payload, config=run_config, stream_mode="updates"):
                    # event is {node_name: state_updates}; state_updates is None when node returns {}
                    for node_name, state_updates in event.items():
                        if node_name == "__interrupt__":
                            question = _interrupt_question(state_updates)
                            continue
                        if not state_updates:
                            continue

                        if node_name in ("reason", "halt"):
                            msgs = state_updates.get("messages", [])
                            last = msgs[-1] if msgs else None
                            if isinstance(last, AIMessage):
                                if last.tool_calls:
                                    names = ", ".join(
                                        _TOOL_LABELS.get(tc["name"], tc["name"])
                                        for tc in last.tool_calls
                                    )
                                    agent_status.write(f"🤔 Planning → {names}")
                                elif isinstance(last.content, str) and last.content:
                                    assistant_text = last.content
                                    text_placeholder.markdown(assistant_text + "▌")
                                    agent_status.write("🤔 Thinking…")

                        elif node_name in ("run_tools", "confirm_and_run"):
                            for msg in state_updates.get("messages", []):
                                if isinstance(msg, ToolMessage):
                                    label = _TOOL_LABELS.get(msg.name, f"🔧 {msg.name or 'tool'}")
                                    content = str(msg.content or "")
                                    preview = content[:80] + ("…" if len(content) > 80 else "")
                                    agent_status.write(f"{label} → {preview}")
                            # Only present when this batch produced a new screenshot
                            if state_updates.get("last_screenshot"):
                                new_screenshot = base64.b64decode(state_updates["last_screenshot"])
                                screenshot_placeholder.image(new_screenshot, use_container_width=True)

                        elif node_name == "post_tool":
                            entries = state_updates.get("feature_tree", [])
                            added = sum(1 for e in entries if e.get("valid", True))
                            removed = len(entries) - added
                            if added:
                                agent_status.write(f"📝 +{added} object(s) added to feature tree")
                            if removed:
                                agent_status.write(f"📝 {removed} object(s) removed from feature tree")

            except Exception as e:
                agent_status.update(label=f"Error: {e}", state="error")
                st.error(f"Agent error: {e}")
                return

            if question is not None:
                agent_status.update(label="⏸️ Waiting for confirmation", state="complete")
            else:
                agent_status.update(label="Done ✓", state="complete")

        if new_screenshot:
            st.session_state.last_screenshot = new_screenshot

        if question is not None:
            st.session_state.messages.append({"role": "assistant", "content": question})
            st.session_state.pending_confirmation = True
            st.rerun()

        # Final text
        text_placeholder.markdown(assistant_text)

        # Show screenshot inline in the message if we got one
        if new_screenshot:
            st.image(new_screenshot, use_container_width=True)

    # Persist to session
    st.session_state.messages.append({
        "role": "assistant",
        "content": assistant_text,
        "screenshot": new_screenshot,
    })

    # Refresh object tree
    _refresh_objects()
    st.session_state.pending_confirmation = False


def _refresh_objects():
    """Pull the current object list from FreeCAD and render it."""
    try:
        st.session_state.objects = get_client(config).list_objects()
    except Exception:
        st.session_state.objects = None
        objects_placeholder.warning("Could not refresh object list.")
        return
    _render_objects()


def _render_objects():
    objs = st.session_state.objects
    if objs is None:
        return
    if objs:
        objects_placeholder.dataframe(
            objs, column_order=("name", "label", "type"), use_container_width=True, hide_index=True
        )
    else:
        objects_placeholder.info("Document is empty.")


# ---------------------------------------------------------------------------
# Main layout — chat on left, screenshot on right
# ---------------------------------------------------------------------------

chat_col, view_col = st.columns([3, 2])

with view_col:
    st.subheader("3D View")
    screenshot_placeholder = st.empty()
    if st.session_state.last_screenshot:
        screenshot_placeholder.image(st.session_state.last_screenshot, use_container_width=True)
    else:
        screenshot_placeholder.info("Screenshot will appear here after each operation.")

    st.subheader("Scene Objects")
    objects_placeholder = st.empty()
    _render_objects()

with chat_col:
    st.subheader("Chat")

    # Config guard
    if not config.is_ready:
        st.warning(
            "No LLM configured. Open **Settings** in the sidebar, "
            "enter your API key, and click **Save Settings**."
        )
        st.stop()

    # Render conversation history
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])
            if msg.get("screenshot"):
                st.image(msg["screenshot"], use_container_width=True)

    # Confirmation UI (shown when graph is interrupted)
    if st.session_state.pending_confirmation:
        st.warning(st.session_state.messages[-1]["content"])
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, proceed", type="primary", use_container_width=True):
                _run_graph("yes", resume=True)
        with c2:
            if st.button("No, cancel", use_container_width=True):
                _run_graph("no", resume=True)
        st.stop()

    # Chat input
    if prompt := st.chat_input("Ask FreeCAD to do something…"):
        _run_graph(prompt)
