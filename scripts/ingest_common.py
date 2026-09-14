"""
Shared pieces of the ingestion pipelines (scripts/ingest.py and
scripts/ingest_tutorials.py): HTML scraping, chunking, and batched upserts
with stable chunk IDs.
"""

import hashlib
from concurrent.futures import ThreadPoolExecutor

import requests
from bs4 import BeautifulSoup
from langchain_chroma import Chroma
from langchain_core.documents import Document
from langchain_text_splitters import RecursiveCharacterTextSplitter
from markdownify import markdownify

from agent.vectorstore import get_vectorstore

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150
BATCH_SIZE = 100
SCRAPE_WORKERS = 6


# ---------------------------------------------------------------------------
# Scraping
# ---------------------------------------------------------------------------

def scrape_html_page(url: str, source_type: str) -> Document | None:
    """Scrape an HTML page and convert to markdown. Works for wiki and external URLs."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  SKIP {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract title
    title_tag = (
        soup.find("h1", {"id": "firstHeading"})  # MediaWiki
        or soup.find("h1")
        or soup.find("title")
    )
    title = title_tag.get_text(strip=True) if title_tag else url.split("/")[-1]

    # Extract main content — try MediaWiki first, fall back to body
    content_div = (
        soup.find("div", {"id": "mw-content-text"})
        or soup.find("main")
        or soup.find("article")
        or soup.find("body")
    )
    if not content_div:
        print(f"  SKIP {url}: no content found")
        return None

    # Strip nav boxes, TOC, edit links
    for tag in content_div.find_all(
        ["div", "table", "span"],
        class_=["noprint", "navbox", "toc", "mw-editsection"],
    ):
        tag.decompose()

    text = markdownify(str(content_div), heading_style="ATX", strip=["a"]).strip()
    if len(text) < 100:
        print(f"  SKIP {url}: content too short")
        return None

    return Document(
        page_content=text,
        metadata={"source": url, "title": title, "type": source_type},
    )


def scrape_pages(urls: list[str], source_type: str) -> list[Document]:
    """Scrape pages concurrently; results keep the order of urls."""
    if not urls:
        return []
    with ThreadPoolExecutor(max_workers=SCRAPE_WORKERS) as pool:
        docs = list(pool.map(lambda url: scrape_html_page(url, source_type), urls))
    for doc in docs:
        if doc:
            print(f"  + {doc.metadata['title']}")
    return [doc for doc in docs if doc]


# ---------------------------------------------------------------------------
# Indexing
# ---------------------------------------------------------------------------

def open_vectorstore(collection_name: str, persist_directory: str, clear: bool) -> Chroma:
    print("Loading embedding model (downloads once on first run)...")
    vectorstore = get_vectorstore(collection_name, persist_directory)
    if clear:
        print(f"Clearing existing collection {collection_name}...")
        try:
            vectorstore._collection.delete(where={"source": {"$ne": ""}})
        except Exception:
            pass  # empty collection
    return vectorstore


def split_documents(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
        add_start_index=True,  # feeds chunk_id
    )
    return splitter.split_documents(docs)


def chunk_id(chunk: Document) -> str:
    """
    Stable ID from where the chunk came from, so re-ingesting a source
    overwrites its chunks instead of adding duplicates.
    """
    m = chunk.metadata
    key = f"{m.get('source', '')}|{m.get('page', '')}|{m.get('start_index', '')}"
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def store_chunks(vectorstore: Chroma, chunks: list[Document]) -> None:
    # Deduplicate first: a source listed twice would repeat an ID within one
    # upsert call, which Chroma rejects.
    unique = {chunk_id(c): c for c in chunks}
    ids, docs = list(unique), list(unique.values())
    for i in range(0, len(docs), BATCH_SIZE):
        vectorstore.add_documents(docs[i:i + BATCH_SIZE], ids=ids[i:i + BATCH_SIZE])
        print(f"  {min(i + BATCH_SIZE, len(docs))}/{len(docs)}")


def index_documents(vectorstore: Chroma, raw_docs: list[Document]) -> int:
    """Chunk, embed and upsert documents; return the collection's new size."""
    print(f"\nChunking {len(raw_docs)} document(s)...")
    chunks = split_documents(raw_docs)
    print(f"  -> {len(chunks)} chunks")

    print("Embedding and storing in ChromaDB...")
    store_chunks(vectorstore, chunks)
    return vectorstore._collection.count()
