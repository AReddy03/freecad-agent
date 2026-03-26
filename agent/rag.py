"""
RAG knowledge layer — ChromaDB + local sentence-transformers embeddings.
No API key required for embeddings.

Usage:
    from agent.rag import build_rag_tool
    rag_tool = build_rag_tool()   # loads or creates the ChromaDB collection
"""

from pathlib import Path
from typing import Annotated

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.tools import tool

CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
COLLECTION_NAME = "freecad_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"  # ~80 MB, downloads once and caches locally

_vectorstore: Chroma | None = None


def _get_vectorstore() -> Chroma:
    global _vectorstore
    if _vectorstore is None:
        embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)
        _vectorstore = Chroma(
            collection_name=COLLECTION_NAME,
            embedding_function=embeddings,
            persist_directory=CHROMA_PATH,
        )
    return _vectorstore


def collection_size() -> int:
    """Return the number of documents indexed."""
    try:
        vs = _get_vectorstore()
        return vs._collection.count()
    except Exception:
        return 0


def build_rag_tool():
    """
    Build and return the rag_search LangChain tool.
    Returns None if ChromaDB has no documents yet (ingest hasn't been run).
    """
    if collection_size() == 0:
        return None

    vs = _get_vectorstore()

    @tool
    def rag_search(
        query: Annotated[str, "Search query for FreeCAD documentation and API reference"]
    ) -> str:
        """Search the FreeCAD documentation knowledge base.
        Use this before writing any script for workbench-specific or unfamiliar operations
        to retrieve the correct Python API, parameters, and examples."""
        docs = vs.similarity_search(query, k=3)
        if not docs:
            return "No relevant documentation found for this query."
        parts = []
        for i, doc in enumerate(docs, 1):
            source = doc.metadata.get("source", "unknown")
            title = doc.metadata.get("title", "")
            header = f"[{i}] {title} ({source})" if title else f"[{i}] {source}"
            parts.append(f"{header}\n{doc.page_content}")
        return "\n\n---\n\n".join(parts)

    return rag_search
