"""
Shared ChromaDB / embedding setup for the API-docs and tutorial collections.

Both collections use the same local sentence-transformers model, so it is
loaded once per process and shared by every vector store.
"""

import threading
from pathlib import Path

from langchain_chroma import Chroma

PROJECT_ROOT = Path(__file__).parent.parent
EMBED_MODEL = "all-MiniLM-L6-v2"  # ~80 MB, downloads once and caches locally

DOCS_CHROMA_PATH = str(PROJECT_ROOT / "chroma_db")
DOCS_COLLECTION = "freecad_docs"

TUTORIALS_CHROMA_PATH = str(PROJECT_ROOT / "chroma_tutorials")
TUTORIALS_COLLECTION = "freecad_tutorials"

_lock = threading.Lock()
_embeddings = None
_stores: dict[tuple[str, str], Chroma] = {}


def get_embeddings():
    """The process-wide embedding model (loaded on first use)."""
    global _embeddings
    with _lock:
        if _embeddings is None:
            # Imported lazily: pulls in torch, which is slow to import.
            from langchain_huggingface import HuggingFaceEmbeddings
            _embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
        return _embeddings


def get_vectorstore(collection_name: str, persist_directory: str) -> Chroma:
    """The cached Chroma store for a collection, created on first use."""
    key = (collection_name, persist_directory)
    embeddings = get_embeddings()
    with _lock:
        if key not in _stores:
            _stores[key] = Chroma(
                collection_name=collection_name,
                embedding_function=embeddings,
                persist_directory=persist_directory,
            )
        return _stores[key]


def collection_size(collection_name: str, persist_directory: str) -> int:
    """Number of chunks indexed in a collection, or 0 if it can't be opened."""
    try:
        return get_vectorstore(collection_name, persist_directory)._collection.count()
    except Exception:
        return 0
