"""
Tutorial RAG — ChromaDB retriever over end-user tutorial documents.

Unlike agent/rag.py (which exposes a LangChain tool for on-demand API lookup),
this module returns a plain VectorStoreRetriever that is called automatically
by the reason node on every turn to inject design guidance into the system prompt.

The tutorial corpus is stored in a separate ChromaDB collection (freecad_tutorials)
so it stays independent of the API documentation in freecad_docs.
"""

from pathlib import Path

from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings

CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_tutorials")
COLLECTION_NAME = "freecad_tutorials"
EMBED_MODEL = "all-MiniLM-L6-v2"  # same model as API docs for consistency

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
    """Return the number of tutorial chunks indexed."""
    try:
        vs = _get_vectorstore()
        return vs._collection.count()
    except Exception:
        return 0


def build_tutorial_retriever():
    """
    Return a VectorStoreRetriever for the tutorial corpus, or None if not ingested.
    Retrieves the top 3 most relevant chunks per query.
    """
    if collection_size() == 0:
        return None
    vs = _get_vectorstore()
    return vs.as_retriever(search_kwargs={"k": 3})
