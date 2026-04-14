# Multi-stage Dockerfile for the FreeCAD Agent.
#
# Stage 1 — ingest: builds the ChromaDB vector store from FreeCAD docs.
# Stage 2 — app:    runs the Streamlit UI.
#
# The vector store is baked into the image so users don't need to run
# ingest.py manually. Re-build the image to refresh the knowledge base.

# ---------------------------------------------------------------------------
# Stage 1 — Ingest FreeCAD documentation
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS ingest

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY agent/ agent/
COPY scripts/ scripts/
COPY data/ data/
COPY tutorial_sources.yaml .

# Build the API docs ChromaDB collection.
# --wiki-only skips the GitHub zip download which can be slow/flaky in CI.
RUN python scripts/ingest.py --wiki-only

# Build the tutorial ChromaDB collection (wiki tutorial pages only).
RUN python scripts/ingest_tutorials.py --type wiki

# ---------------------------------------------------------------------------
# Stage 2 — Application
# ---------------------------------------------------------------------------
FROM python:3.11-slim AS app

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy source
COPY agent/ agent/
COPY ui/ ui/
COPY scripts/ scripts/
COPY skills/ skills/

# Copy the pre-built vector stores from stage 1
COPY --from=ingest /app/chroma_db ./chroma_db
COPY --from=ingest /app/chroma_tutorials ./chroma_tutorials

# User config is mounted at runtime via docker-compose volume
# (see docker-compose.yml) — the container writes to /root/.freecad-agent/

EXPOSE 8501

# Connect to FreeCAD on the host machine.
# On Windows/Mac: host.docker.internal resolves automatically.
# On Linux: add --add-host=host-gateway:host-gateway to docker run, then use
#           FREECAD_HOST=host-gateway in the settings.
ENV FREECAD_HOST=host.docker.internal
ENV FREECAD_PORT=65432

HEALTHCHECK --interval=30s --timeout=10s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

CMD ["streamlit", "run", "ui/app.py", \
     "--server.port=8501", \
     "--server.address=0.0.0.0", \
     "--server.headless=true", \
     "--browser.gatherUsageStats=false"]
