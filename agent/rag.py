"""
RAG knowledge layer — ChromaDB + local sentence-transformers embeddings.
No API key required for embeddings.

Usage:
    from agent.rag import build_rag_tool
    rag_tool = build_rag_tool()   # loads or creates the ChromaDB collection
"""

from typing import Annotated

from langchain_core.tools import tool

from agent import vectorstore
from agent.vectorstore import DOCS_CHROMA_PATH, DOCS_COLLECTION


def collection_size() -> int:
    """Return the number of documents indexed."""
    return vectorstore.collection_size(DOCS_COLLECTION, DOCS_CHROMA_PATH)


def build_rag_tool():
    """
    Build and return the rag_search LangChain tool.
    Returns None if ChromaDB has no documents yet (ingest hasn't been run).
    """
    if collection_size() == 0:
        return None

    vs = vectorstore.get_vectorstore(DOCS_COLLECTION, DOCS_CHROMA_PATH)

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
