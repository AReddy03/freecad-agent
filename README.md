# FreeCAD Agent

An agentic AI assistant for FreeCAD. Give it natural-language CAD requests and it acts directly inside FreeCAD — creating geometry, modifying objects, and verifying its own work with screenshots. The agent accumulates long-term memory across sessions and draws on a built-in library of CAD best-practice skills.

## Architecture

```
Streamlit UI  →  LangGraph agent  →  FreeCAD (TCP socket, port 65432)
                      ↓
         ┌────────────────────────────┐
         │  System prompt (per turn)  │
         │  ─────────────────────     │
         │  Long-term memory          │  ~/.freecad-agent/memory.db
         │  Skills index + guidance   │  skills/*/SKILL.md
         │  Tutorial RAG (optional)   │  chroma_tutorials/
         │  API docs RAG              │  chroma_db/
         │  Feature tree (session)    │  checkpoints.db
         └────────────────────────────┘
```

- **LLM**: Anthropic Claude, OpenAI GPT-4o, Google Gemini, or local Ollama — swappable via Settings
- **Agent loop**: LangGraph StateGraph (ReAct pattern with human-in-the-loop confirmation for destructive ops)
- **FreeCAD interface**: Direct TCP socket connection to the FreeCAD MCP addon
- **RAG**: FreeCAD wiki + GitHub docs, local embeddings (no API key for search)
- **Memory**: SQLite-backed cross-session memory — preferences, patterns, session summaries
- **Skills**: Curated CAD best-practice guidance injected when relevant to the current request

## Features

### Long-term Memory

The agent remembers across sessions. At the end of every task it saves a session summary automatically. The agent can also explicitly save facts via the `memory_save` tool — user preferences, successful script patterns, or anything you ask it to remember.

Memory is stored in `~/.freecad-agent/memory.db` (SQLite with FTS5 full-text search) and injected into every system prompt automatically.

**Example:**
> *"Remember that I always work in millimetres and prefer the Part workbench"* → saved as a preference, recalled in every future session.

### CAD Skills Library

Six built-in skill documents encode professional CAD best practices. The agent knows what skills are available every turn and loads the relevant guidance when your request matches:

| Skill | Triggers on |
|---|---|
| `sketching-and-constraints` | sketches, constraints, 2D profiles, dimensions |
| `feature-tree-strategy` | feature order, rebuild failures, model organisation |
| `parametric-modeling` | extrude, revolve, loft, parameters, design intent |
| `assembly-design` | assembly, mates, sub-assemblies, top-down design |
| `design-for-manufacturing` | DFM, wall thickness, draft angle, CNC, molding, 3D printing |
| `tolerancing-and-gdt` | tolerances, GD&T, datums, true position, fits |

The agent can also call `skill_search` to pull the full content of any skill on demand.

### Human-in-the-loop Safety

Destructive operations (`clear_document`, `save_document` to an existing path) always pause and ask for confirmation before executing.

### Visual Verification

After every script execution the agent captures a screenshot and shows it inline in the chat, then self-corrects if the result doesn't match the request.

## Developer Setup

```bash
# 1. Clone
git clone https://github.com/AReddy03/freecad-agent && cd freecad-agent

# 2. Virtual environment
python -m venv .venv
.venv\Scripts\activate        # Windows
source .venv/bin/activate     # macOS/Linux

# 3. Dependencies
pip install -r requirements.txt

# 4. Build knowledge base (downloads FreeCAD docs, ~5 min first run)
python scripts/ingest.py

# 5. Health check
python scripts/test_connection.py

# 6. Run
streamlit run ui/app.py
```

Configure your API key and FreeCAD connection via the **Settings** sidebar on first launch.

## Project Structure

```
agent/
  config.py          # UserConfig, load/save ~/.freecad-agent/config.json
  state.py           # AgentState schema and LangGraph reducers
  graph.py           # LangGraph StateGraph (nodes, edges, routing)
  llm.py             # get_llm() factory — Anthropic | OpenAI | Google | Ollama
  freecad_client.py  # TCP socket RPC client for FreeCAD
  tools.py           # LangChain @tool wrappers (FreeCAD + memory + skills)
  memory.py          # MemoryStore — SQLite FTS5 cross-session memory
  skills.py          # SkillsRegistry — loads and matches SKILL.md files
  rag.py             # ChromaDB client + rag_search tool (API docs)
  tutorial_rag.py    # Tutorial retriever (optional, toggle in Settings)
  safety.py          # Destructive operation classifier
  prompts.py         # System prompt + context formatting functions

skills/
  sketching-and-constraints/SKILL.md
  feature-tree-strategy/SKILL.md
  parametric-modeling/SKILL.md
  assembly-design/SKILL.md
  design-for-manufacturing/SKILL.md
  tolerancing-and-gdt/SKILL.md

ui/
  app.py             # Streamlit frontend (chat, 3D view, memory/skills panels)

scripts/
  ingest.py          # API doc ingestion pipeline (FreeCAD wiki + GitHub)
  ingest_tutorials.py # Tutorial corpus ingestion
  test_connection.py # Health check

tests/
  test_state.py      # State schema and reducer tests
  test_memory.py     # MemoryStore unit tests
  test_skills.py     # SkillsRegistry unit tests
```

## Runtime Data

| Path | Contents |
|---|---|
| `~/.freecad-agent/config.json` | LLM provider, model, API key, FreeCAD host/port |
| `~/.freecad-agent/memory.db` | Cross-session memory (SQLite) |
| `checkpoints.db` | Per-session graph state (LangGraph checkpointer) |
| `chroma_db/` | FreeCAD API docs vector store |
| `chroma_tutorials/` | Tutorial corpus vector store |

## End-User Installation

See [INSTALL.md](INSTALL.md).

## Adding a New LLM Provider

1. Add the provider name and models to `PROVIDER_MODELS` in `agent/config.py`
2. Add a `case` to `get_llm()` in `agent/llm.py`
3. Add the `langchain-<provider>` package to `requirements.txt`

That's all — the rest of the codebase is provider-agnostic.

## Adding More Documentation Sources

Edit `scripts/ingest.py`:
- Add URLs to `WIKI_PAGES` for additional wiki pages
- Add sub-folder names to `GITHUB_INCLUDE_DIRS` for GitHub doc sections
- Or add an entirely new source block following the `_scrape_wiki_page` pattern

Re-run `python scripts/ingest.py` (or rebuild the Docker image) to update the knowledge base.

## Adding a New Skill

Create a new directory under `skills/` with a `SKILL.md` file:

```markdown
---
name: my-skill-name
description: >
  One or two sentences describing what this skill covers and what user
  requests should trigger it. Include key trigger words here.
---

# My Skill — Best Practices

Full markdown content...
```

The skill is picked up automatically on next startup — no code changes needed.

## Running Tests

```bash
python -m pytest tests/ -v
```
