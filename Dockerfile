# Multi-stage Dockerfile for the FreeCAD Agent.
#
# Stage 1 — base:   runtime Python deps (CPU-only torch), shared by both later stages.
# Stage 2 — ingest: builds the ChromaDB vector stores and downloads the embedding model.
# Stage 3 — app:    runs the Streamlit UI.
#
# The vector stores and the embedding model are baked into the image so users
# don't need to run the ingest scripts or download anything on first start.
# Re-build the image to refresh the knowledge base.

# ---------------------------------------------------------------------------
# Stage 1 — Runtime dependencies
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS base

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HF_HOME=/opt/hf-cache

# CPU-only torch first. sentence-transformers would otherwise pull the default
# PyPI wheel, which bundles several GB of CUDA libraries.
RUN pip install torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2 — Ingest FreeCAD documentation
# ---------------------------------------------------------------------------
FROM base AS ingest

COPY requirements-ingest.txt .
RUN pip install -r requirements-ingest.txt

COPY agent/ agent/
COPY scripts/ scripts/
COPY tutorial_sources.yaml .

# Build the API docs ChromaDB collection.
# --wiki-only skips the GitHub zip download which can be slow/flaky in CI.
RUN python scripts/ingest.py --wiki-only

# Build the tutorial ChromaDB collection (wiki tutorial pages only).
RUN python scripts/ingest_tutorials.py --type wiki

# ---------------------------------------------------------------------------
# Stage 3 — Application
# ---------------------------------------------------------------------------
FROM base AS app

# Copy source
COPY agent/ agent/
COPY ui/ ui/
COPY scripts/ scripts/
COPY skills/ skills/

# Pre-built vector stores and the embedding model cache from stage 2
COPY --from=ingest /app/chroma_db ./chroma_db
COPY --from=ingest /app/chroma_tutorials ./chroma_tutorials
COPY --from=ingest /opt/hf-cache /opt/hf-cache

# User config is mounted at runtime via docker-compose volume
# (see docker-compose.yml) — the container writes to /root/.freecad-agent/

EXPOSE 8501

# Connect to FreeCAD on the host machine. These override the host/port saved
# in the Settings panel.
# On Windows/Mac: host.docker.internal resolves automatically.
# On Linux: add --add-host=host-gateway:host-gateway to docker run, then use
#           FREECAD_HOST=host-gateway.
ENV FREECAD_HOST=host.docker.internal \
    FREECAD_PORT=65432 \
    CHECKPOINTS_DB=/app/state/checkpoints.db

# python:3.11-slim has no curl, so probe the health endpoint with Python.
HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health', timeout=5)" || exit 1

CMD ["streamlit", "run", "ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
