"""
FreeCAD Agent — Streamlit UI

Layout:
  Sidebar  — Settings (provider, model, API key, connection test)
  Main col — Chat window + streamed responses
  Right col — Live screenshot + object tree
"""

import base64
import sys
import uuid
from pathlib import Path

import streamlit as st

# Ensure project root is on the path when running via `streamlit run ui/app.py`
sys.path.insert(0, str(Path(__file__).parent.parent))

from agent.config import PROVIDER_MODELS, UserConfig, load_config, save_config
from agent.llm import is_ollama_running, list_ollama_models
from agent.rag import build_rag_tool, collection_size

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
# Session state defaults
# ---------------------------------------------------------------------------

if "thread_id" not in st.session_state:
    st.session_state.thread_id = str(uuid.uuid4())
if "messages" not in st.session_state:
    st.session_state.messages = []  # list of {"role": str, "content": str, "screenshot": str|None}
if "graph" not in st.session_state:
    st.session_state.graph = None
if "last_screenshot" not in st.session_state:
    st.session_state.last_screenshot = None
if "pending_confirmation" not in st.session_state:
    st.session_state.pending_confirmation = False  # True when graph is interrupted

# ---------------------------------------------------------------------------
# Sidebar — Settings
# ---------------------------------------------------------------------------

with st.sidebar:
    st.title("⚙️ FreeCAD Agent")
    st.divider()

    st.subheader("LLM Settings")

    config: UserConfig = load_config()

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
        ollama_ok = is_ollama_running()
        if ollama_ok:
            st.success("Ollama detected")
            available_models = list_ollama_models() or ["(no models pulled)"]
        else:
            st.warning("Ollama not detected — is it running?")
            available_models = ["(ollama not running)"]
        model_options = available_models
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
    freecad_host = st.text_input("Host", value=config.freecad_host)
    freecad_port = st.number_input("Port", value=config.freecad_port, min_value=1, max_value=65535)

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Settings", use_container_width=True):
            new_config = UserConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                freecad_host=freecad_host,
                freecad_port=int(freecad_port),
            )
            save_config(new_config)
            # Reset graph so it rebuilds with new config
            st.session_state.graph = None
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
            _errors = []

            # Test FreeCAD
            try:
                from agent.freecad_client import FreeCADClient
                c = FreeCADClient(host=freecad_host, port=int(freecad_port))
                c.connect()
                c.disconnect()
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
    n = collection_size()
    if n == 0:
        st.warning("Not indexed yet. Run:\n```\npython scripts/ingest.py\n```")
    else:
        st.success(f"{n} chunks indexed")

    # Session controls
    st.divider()
    if st.button("New Session", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.last_screenshot = None
        st.session_state.pending_confirmation = False
        st.session_state.graph = None
        st.rerun()

# ---------------------------------------------------------------------------
# Lazy graph initialisation
# ---------------------------------------------------------------------------

def _get_graph():
    if st.session_state.graph is None:
        cfg = load_config()
        if not cfg.is_ready:
            return None
        from agent.graph import build_graph
        rag_tool = build_rag_tool()
        st.session_state.graph = build_graph(cfg, rag_tool=rag_tool)
    return st.session_state.graph


# ---------------------------------------------------------------------------
# Graph runner  (defined before layout so calls below can reference it)
# ---------------------------------------------------------------------------

def _run_graph(user_input: str):
    """Invoke the graph with user_input and update session state."""
    from langchain_core.messages import HumanMessage

    graph = _get_graph()
    if not graph:
        st.error("Agent not ready — check settings.")
        return

    # Add user message to display
    st.session_state.messages.append({"role": "user", "content": user_input})

    run_config = {"configurable": {"thread_id": st.session_state.thread_id}}
    input_payload = {"messages": [HumanMessage(content=user_input)]}

    assistant_text = ""
    new_screenshot = None

    with st.chat_message("assistant"):
        text_placeholder = st.empty()

        try:
            for event in graph.stream(input_payload, config=run_config, stream_mode="values"):
                state = event

                # Stream assistant tokens
                msgs = state.get("messages", [])
                if msgs:
                    last = msgs[-1]
                    role = getattr(last, "type", "")
                    if role == "ai":
                        content = last.content
                        if isinstance(content, str) and content:
                            assistant_text = content
                            text_placeholder.markdown(assistant_text + "▌")

                # Capture screenshot updates
                if state.get("last_screenshot"):
                    new_screenshot = state["last_screenshot"]
                    png = base64.b64decode(new_screenshot)
                    screenshot_placeholder.image(png, use_container_width=True)

        except Exception as e:
            error_str = str(e)
            # LangGraph raises when the graph hits an interrupt
            if "interrupt" in error_str.lower() or "GraphInterrupt" in type(e).__name__:
                # Extract the confirmation question from graph state
                current_state = graph.get_state(run_config)
                interrupts = current_state.tasks
                question = "Confirm this action?"
                for task in interrupts:
                    for iv in getattr(task, "interrupts", []):
                        if isinstance(iv.value, dict):
                            question = iv.value.get("question", question)
                        elif isinstance(iv.value, str):
                            question = iv.value
                st.session_state.messages.append({"role": "assistant", "content": question})
                st.session_state.pending_confirmation = True
                st.rerun()
                return
            else:
                st.error(f"Agent error: {e}")
                return

        # Final text
        text_placeholder.markdown(assistant_text)

        # Show screenshot inline in the message if we got one
        if new_screenshot:
            png = base64.b64decode(new_screenshot)
            st.image(png, use_container_width=True)

    # Persist to session
    st.session_state.messages.append({
        "role": "assistant",
        "content": assistant_text,
        "screenshot": new_screenshot,
    })
    if new_screenshot:
        st.session_state.last_screenshot = new_screenshot

    # Refresh object tree
    _refresh_objects()
    st.session_state.pending_confirmation = False


def _refresh_objects():
    """Pull the current object list from FreeCAD and render it."""
    try:
        cfg = load_config()
        from agent.freecad_client import FreeCADClient
        c = FreeCADClient(host=cfg.freecad_host, port=cfg.freecad_port)
        c.connect()
        objs = c.list_objects()
        c.disconnect()
        if objs:
            import pandas as pd
            df = pd.DataFrame(objs)[["name", "label", "type"]]
            objects_placeholder.dataframe(df, use_container_width=True, hide_index=True)
        else:
            objects_placeholder.info("Document is empty.")
    except Exception:
        objects_placeholder.warning("Could not refresh object list.")


# ---------------------------------------------------------------------------
# Main layout — chat on left, screenshot on right
# ---------------------------------------------------------------------------

chat_col, view_col = st.columns([3, 2])

with view_col:
    st.subheader("3D View")
    screenshot_placeholder = st.empty()
    if st.session_state.last_screenshot:
        png = base64.b64decode(st.session_state.last_screenshot)
        screenshot_placeholder.image(png, use_container_width=True)
    else:
        screenshot_placeholder.info("Screenshot will appear here after each operation.")

    st.subheader("Scene Objects")
    objects_placeholder = st.empty()

with chat_col:
    st.subheader("Chat")

    # Config guard
    cfg = load_config()
    if not cfg.is_ready:
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
                png = base64.b64decode(msg["screenshot"])
                st.image(png, use_container_width=True)

    # Confirmation UI (shown when graph is interrupted)
    if st.session_state.pending_confirmation:
        st.warning(st.session_state.messages[-1]["content"])
        c1, c2 = st.columns(2)
        with c1:
            if st.button("Yes, proceed", type="primary", use_container_width=True):
                _run_graph("yes")
        with c2:
            if st.button("No, cancel", use_container_width=True):
                _run_graph("no")
        st.stop()

    # Chat input
    if prompt := st.chat_input("Ask FreeCAD to do something…"):
        _run_graph(prompt)
