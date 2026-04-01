# FreeCAD Agent — Installation Guide

Get the AI assistant running in 3 steps.

---

## Prerequisites

- **FreeCAD 0.21+** installed and open
- **FreeCAD MCP addon** installed inside FreeCAD (provides the AI bridge)
- **Docker Desktop** installed — [download here](https://www.docker.com/products/docker-desktop/)

---

## Step 1 — Install the FreeCAD MCP Addon

1. Open FreeCAD
2. Go to **Tools → Addon Manager**
3. Search for **FreeCAD MCP** and install it
4. Restart FreeCAD
5. You should see `[FreeCAD MCP] RPC server listening on 127.0.0.1:65432` in the FreeCAD console

> The addon must be running whenever you use the agent. Keep FreeCAD open.

---

## Step 2 — Start the Agent

Open a terminal and run:

**Windows (PowerShell or CMD):**
```bash
docker run --pull=always -p 8501:8501 ^
  --add-host=host.docker.internal:host-gateway ^
  -v "%USERPROFILE%\.freecad-agent:/root/.freecad-agent" ^
  ghcr.io/areddy03/freecad-agent:latest
```

**macOS / Linux:**
```bash
docker run --pull=always -p 8501:8501 \
  --add-host=host.docker.internal:host-gateway \
  -v "$HOME/.freecad-agent:/root/.freecad-agent" \
  ghcr.io/areddy03/freecad-agent:latest
```

> After starting, open Settings and set **FreeCAD Host** to `host.docker.internal` (not `127.0.0.1`). Docker containers cannot reach the host machine via `127.0.0.1`.

---

## Step 3 — Configure Your API Key

1. Open **http://localhost:8501** in your browser
2. In the **Settings** sidebar:
   - Choose your LLM provider (Anthropic, OpenAI, or Ollama)
   - Enter your API key
   - Click **Save Settings**
3. Click **Test Connection** — both FreeCAD and your LLM should show green

You're ready. Type a request in the chat, e.g.:
*"Create a 50×30×10mm box with a 3mm fillet on all top edges"*

---

## Using Ollama (free, local, no API key)

1. Install Ollama from [ollama.com](https://ollama.com)
2. Pull a model: `ollama pull llama3.2`
3. In Settings, select **Provider: ollama** — the model list auto-populates
4. No API key needed

> Ollama runs on your machine. Responses are slower than cloud APIs but completely free and private.

---

## Updating the Knowledge Base

The agent's FreeCAD documentation is baked into the Docker image at build time.
To get the latest docs, rebuild the image:

```bash
docker build -t freecad-agent:latest .
```

---

## Alternative: Run Without Docker

```bash
git clone <repo>
cd freecad-agent
python -m venv .venv && .venv\Scripts\activate   # Windows
pip install -r requirements.txt
python scripts/ingest.py                          # build knowledge base (~5 min)
streamlit run ui/app.py
```
