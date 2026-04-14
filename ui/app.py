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
from agent.tutorial_rag import build_tutorial_retriever, collection_size as tutorial_collection_size

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
    if use_tutorial_rag and tutorial_collection_size() == 0:
        st.warning(
            "Tutorial corpus not indexed yet. Run:\n```\npython scripts/ingest_tutorials.py\n```"
        )

    st.divider()
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Save Settings", use_container_width=True):
            new_config = UserConfig(
                provider=provider,
                model=model,
                api_key=api_key,
                freecad_host=freecad_host,
                freecad_port=int(freecad_port),
                use_tutorial_rag=use_tutorial_rag,
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
        st.warning("API docs not indexed. Run:\n```\npython scripts/ingest.py\n```")
    else:
        st.success(f"API docs: {n} chunks")
    tn = tutorial_collection_size()
    if tn > 0:
        st.success(f"Tutorials: {tn} chunks")

    # Memory status
    st.divider()
    st.subheader("Memory")
    try:
        from agent.memory import get_memory_store
        _ms = get_memory_store()
        _n_mem = _ms.count()
        if _n_mem == 0:
            st.info("No memories yet. The agent learns as you work.")
        else:
            st.success(f"{_n_mem} memor{'y' if _n_mem == 1 else 'ies'} stored")
        with st.expander("View recent memories", expanded=False):
            _recent = _ms.get_recent(limit=10)
            if _recent:
                for _m in _recent:
                    st.caption(f"[{_m['memory_type']}] {_m['content'][:100]}")
            else:
                st.caption("Nothing saved yet.")
    except Exception as _e:
        st.warning(f"Memory store unavailable: {_e}")

    # Skills status
    st.divider()
    st.subheader("Skills")
    try:
        from agent.skills import get_skills_registry
        _sr = get_skills_registry()
        _all_skills = _sr.list_all()
        if _all_skills:
            st.success(f"{len(_all_skills)} skill{'s' if len(_all_skills) != 1 else ''} loaded")
        else:
            st.warning("No skills loaded. Add SKILL.md files to the skills/ directory.")
        with st.expander("Browse skills", expanded=False):
            for _s in _all_skills:
                first_sentence = _s["description"].split(".")[0].strip()
                st.caption(f"**{_s['name']}** — {first_sentence[:80]}")
    except Exception as _e:
        st.warning(f"Skills registry unavailable: {_e}")

    # Session controls
    st.divider()
    if st.button("New Session", use_container_width=True):
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.messages = []
        st.session_state.last_screenshot = None
        st.session_state.pending_confirmation = False
        st.session_state.graph = None
        st.rerun()

    if st.button("Clear Document", use_container_width=True):
        try:
            cfg = load_config()
            from agent.freecad_client import FreeCADClient
            c = FreeCADClient(host=cfg.freecad_host, port=cfg.freecad_port)
            c.connect()
            c.clear_document()
            c.disconnect()
            st.success("Document cleared.")
        except Exception as e:
            st.error(f"Could not clear document: {e}")
        # New thread forces a fresh feature_tree in graph state
        st.session_state.thread_id = str(uuid.uuid4())
        st.session_state.graph = None
        st.session_state.last_screenshot = None
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
        from agent.memory import get_memory_store
        from agent.skills import get_skills_registry
        rag_tool = build_rag_tool()
        tutorial_retriever = build_tutorial_retriever() if cfg.use_tutorial_rag else None
        memory_store = get_memory_store()
        skills_registry = get_skills_registry()
        st.session_state.graph = build_graph(
            cfg,
            rag_tool=rag_tool,
            tutorial_retriever=tutorial_retriever,
            memory_store=memory_store,
            skills_registry=skills_registry,
        )
    return st.session_state.graph


# ---------------------------------------------------------------------------
# Graph runner  (defined before layout so calls below can reference it)
# ---------------------------------------------------------------------------

_TOOL_LABELS = {
    "execute_script":   "⚙️ Executing script",
    "get_screenshot":   "📸 Taking screenshot",
    "list_objects":     "🔍 Listing objects",
    "get_feature_tree": "🌳 Checking feature tree",
    "rag_search":       "📚 Searching docs",
    "clear_document":   "🗑️ Clearing document",
    "save_document":    "💾 Saving document",
    "memory_save":      "🧠 Saving to memory",
    "skill_search":     "🔧 Searching skills library",
}


def _run_graph(user_input: str):
    """Invoke the graph with user_input and update session state."""
    from langchain_core.messages import HumanMessage, AIMessage, ToolMessage

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

        with st.status("Agent running…", expanded=True) as agent_status:
            try:
                for event in graph.stream(input_payload, config=run_config, stream_mode="updates"):
                    # event is {node_name: state_updates}; state_updates is None when node returns {}
                    for node_name, state_updates in event.items():
                        if not state_updates:
                            continue
                        if node_name == "reason":
                            msgs = state_updates.get("messages", [])
                            if msgs:
                                last = msgs[-1]
                                if isinstance(last, AIMessage):
                                    tool_calls = getattr(last, "tool_calls", [])
                                    if tool_calls:
                                        names = ", ".join(
                                            _TOOL_LABELS.get(tc["name"], tc["name"])
                                            for tc in tool_calls
                                        )
                                        agent_status.write(f"🤔 Planning → {names}")
                                    else:
                                        content = last.content
                                        if isinstance(content, str) and content:
                                            assistant_text = content
                                            text_placeholder.markdown(assistant_text + "▌")
                                            agent_status.write("🤔 Thinking…")

                        elif node_name in ("run_tools", "confirm_and_run"):
                            msgs = state_updates.get("messages", [])
                            for msg in msgs:
                                if isinstance(msg, ToolMessage):
                                    label = _TOOL_LABELS.get(
                                        getattr(msg, "name", ""), f"🔧 {getattr(msg, 'name', 'tool')}"
                                    )
                                    preview = (msg.content or "")[:80]
                                    if len(msg.content or "") > 80:
                                        preview += "…"
                                    agent_status.write(f"{label} → {preview}")
                            # Capture screenshot updates
                            if state_updates.get("last_screenshot"):
                                new_screenshot = state_updates["last_screenshot"]
                                png = base64.b64decode(new_screenshot)
                                screenshot_placeholder.image(png, use_container_width=True)

                        elif node_name == "post_tool":
                            new_entries = state_updates.get("feature_tree", [])
                            if new_entries:
                                agent_status.write(f"📝 +{len(new_entries)} object(s) added to feature tree")

            except Exception as e:
                error_str = str(e)
                # LangGraph raises when the graph hits an interrupt
                if "interrupt" in error_str.lower() or "GraphInterrupt" in type(e).__name__:
                    agent_status.update(label="⏸️ Waiting for confirmation", state="complete")
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
                    agent_status.update(label=f"Error: {e}", state="error")
                    st.error(f"Agent error: {e}")
                    return

            agent_status.update(label="Done ✓", state="complete")

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
