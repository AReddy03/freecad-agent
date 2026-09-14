"""
Tutorial RAG — ChromaDB retriever over end-user tutorial documents.

Unlike agent/rag.py (which exposes a LangChain tool for on-demand API lookup),
this module returns a plain VectorStoreRetriever that the reason node calls
automatically to inject design guidance into the system prompt.

The tutorial corpus is stored in a separate ChromaDB collection (freecad_tutorials)
so it stays independent of the API documentation in freecad_docs.
"""

from agent import vectorstore
from agent.vectorstore import TUTORIALS_CHROMA_PATH, TUTORIALS_COLLECTION


def collection_size() -> int:
    """Return the number of tutorial chunks indexed."""
    return vectorstore.collection_size(TUTORIALS_COLLECTION, TUTORIALS_CHROMA_PATH)


def build_tutorial_retriever():
    """
    Return a VectorStoreRetriever for the tutorial corpus, or None if not ingested.
    Retrieves the top 3 most relevant chunks per query.
    """
    if collection_size() == 0:
        return None
    vs = vectorstore.get_vectorstore(TUTORIALS_COLLECTION, TUTORIALS_CHROMA_PATH)
    return vs.as_retriever(search_kwargs={"k": 3})
