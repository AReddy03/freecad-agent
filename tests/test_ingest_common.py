"""Tests for the shared ingestion helpers (chunk IDs and idempotent upserts)."""

import itertools

from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_core.embeddings import FakeEmbeddings

from scripts.ingest_common import chunk_id, split_documents, store_chunks

_collection_names = itertools.count()


def make_store() -> Chroma:
    # In-memory Chroma; a unique collection per test keeps them isolated.
    return Chroma(
        collection_name=f"test_{next(_collection_names)}",
        embedding_function=FakeEmbeddings(size=8),
    )


def sample_docs() -> list[Document]:
    text = "\n\n".join(f"Paragraph {i}: " + "word " * 60 for i in range(10))
    return [
        Document(page_content=text, metadata={"source": "https://wiki.example/a"}),
        Document(page_content=text, metadata={"source": "https://wiki.example/b"}),
    ]


def test_chunk_ids_are_stable_and_distinct():
    first = [chunk_id(c) for c in split_documents(sample_docs())]
    second = [chunk_id(c) for c in split_documents(sample_docs())]
    assert len(first) > 2
    assert first == second
    assert len(set(first)) == len(first)


def test_reingesting_does_not_duplicate_chunks():
    store = make_store()
    chunks = split_documents(sample_docs())
    store_chunks(store, chunks)
    store_chunks(store, split_documents(sample_docs()))
    assert store._collection.count() == len(chunks)


def test_duplicate_sources_in_one_run_are_collapsed():
    store = make_store()
    once = split_documents(sample_docs())
    store_chunks(store, once + split_documents(sample_docs()))
    assert store._collection.count() == len(once)
