# FreeCAD Agent

An agentic AI assistant for FreeCAD. Give it natural-language CAD requests and it acts directly inside FreeCAD — creating geometry, modifying objects, and verifying its own work with screenshots.

## Architecture

```
Streamlit UI  →  LangGraph agent  →  FreeCAD (TCP socket, port 65432)
                      ↓
               RAG knowledge base (ChromaDB + sentence-transformers)
```

- **LLM**: Anthropic Claude, OpenAI GPT-4o, or local Ollama — swappable via Settings
- **Agent loop**: LangGraph StateGraph (ReAct pattern with human-in-the-loop confirmation)
- **FreeCAD interface**: Direct TCP socket connection to the FreeCAD MCP addon
- **RAG**: FreeCAD wiki + GitHub docs, local embeddings (no API key for search)

## Developer Setup

```bash
# 1. Clone
git clone <repo> && cd freecad-agent

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
  llm.py             # get_llm() factory — Anthropic | OpenAI | Ollama
  freecad_client.py  # TCP socket client for the FreeCAD RPC server
  tools.py           # LangChain @tool wrappers over FreeCADClient
  rag.py             # ChromaDB client + rag_search tool
  safety.py          # Destructive operation classifier
  prompts.py         # System prompt
  graph.py           # LangGraph StateGraph
ui/
  app.py             # Streamlit frontend
scripts/
  ingest.py          # Doc ingestion pipeline
  test_connection.py # Health check
```

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
