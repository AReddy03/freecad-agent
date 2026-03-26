"""
FreeCAD documentation ingestion pipeline.

Sources:
  1. FreeCAD wiki  — key pages scraped via HTTP
  2. FreeCAD-documentation GitHub repo — downloaded as a zip and extracted

Run:
    python scripts/ingest.py              # ingest all sources
    python scripts/ingest.py --wiki-only  # wiki only
    python scripts/ingest.py --github-only
    python scripts/ingest.py --clear      # wipe ChromaDB and re-ingest
"""

import argparse
import io
import sys
import zipfile
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain_core.documents import Document
from markdownify import markdownify

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

CHROMA_PATH = str(Path(__file__).parent.parent / "chroma_db")
COLLECTION_NAME = "freecad_docs"
EMBED_MODEL = "all-MiniLM-L6-v2"

CHUNK_SIZE = 800
CHUNK_OVERLAP = 150

# Wiki pages to scrape — covers the most commonly needed APIs
WIKI_PAGES = [
    # Core scripting
    "https://wiki.freecad.org/FreeCAD_Scripting_Basics",
    "https://wiki.freecad.org/Introduction_to_Python",
    "https://wiki.freecad.org/Python_scripting_tutorial",
    # Part workbench
    "https://wiki.freecad.org/Part_scripting",
    "https://wiki.freecad.org/Topological_data_scripting",
    "https://wiki.freecad.org/Part_Box",
    "https://wiki.freecad.org/Part_Cylinder",
    "https://wiki.freecad.org/Part_Sphere",
    "https://wiki.freecad.org/Part_Cone",
    "https://wiki.freecad.org/Part_Torus",
    "https://wiki.freecad.org/Part_Fillet",
    "https://wiki.freecad.org/Part_Chamfer",
    "https://wiki.freecad.org/Part_Boolean",
    "https://wiki.freecad.org/Part_Cut",
    "https://wiki.freecad.org/Part_Fuse",
    "https://wiki.freecad.org/Part_Common",
    "https://wiki.freecad.org/Part_Extrude",
    "https://wiki.freecad.org/Part_Revolve",
    "https://wiki.freecad.org/Part_Mirror",
    "https://wiki.freecad.org/Part_Sweep",
    "https://wiki.freecad.org/Part_Loft",
    # PartDesign workbench
    "https://wiki.freecad.org/PartDesign_scripting",
    "https://wiki.freecad.org/PartDesign_Pad",
    "https://wiki.freecad.org/PartDesign_Pocket",
    "https://wiki.freecad.org/PartDesign_Fillet",
    "https://wiki.freecad.org/PartDesign_Chamfer",
    "https://wiki.freecad.org/PartDesign_Boolean",
    # Sketcher workbench
    "https://wiki.freecad.org/Sketcher_scripting",
    # Draft workbench
    "https://wiki.freecad.org/Draft_scripting",
    "https://wiki.freecad.org/Draft_Wire",
    "https://wiki.freecad.org/Draft_Line",
    "https://wiki.freecad.org/Draft_Circle",
    "https://wiki.freecad.org/Draft_Rectangle",
    # Mesh workbench
    "https://wiki.freecad.org/Mesh_scripting",
    # Document / object model
    "https://wiki.freecad.org/Scripted_objects",
    "https://wiki.freecad.org/Property",
    "https://wiki.freecad.org/App_DocumentObject",
]

# FreeCAD-documentation GitHub repo (markdown files)
GITHUB_ZIP_URL = (
    "https://github.com/FreeCAD/FreeCAD-documentation/archive/refs/heads/main.zip"
)
# Only ingest these sub-folders from the repo (keeps scope tight)
GITHUB_INCLUDE_DIRS = {
    "python_scripting_tutorial",
    "part_scripting",
    "partdesign_scripting",
    "sketcher_scripting",
    "draft_scripting",
    "freecad_scripting_basics",
    "introduction_to_python",
    "scripted_objects",
    "topological_data_scripting",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _scrape_wiki_page(url: str) -> Document | None:
    """Download one wiki page and return a LangChain Document, or None on error."""
    try:
        resp = requests.get(url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        print(f"  SKIP {url}: {e}")
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract the article title
    title_tag = soup.find("h1", {"id": "firstHeading"})
    title = title_tag.get_text(strip=True) if title_tag else url.split("/")[-1]

    # Extract the main article body
    content_div = soup.find("div", {"id": "mw-content-text"})
    if not content_div:
        return None

    # Remove navigation boxes, footers, edit buttons
    for tag in content_div.find_all(["div", "table"], class_=["noprint", "navbox", "toc"]):
        tag.decompose()

    text = markdownify(str(content_div), heading_style="ATX", strip=["a"])
    text = text.strip()

    if len(text) < 100:
        return None

    return Document(
        page_content=text,
        metadata={"source": url, "title": title, "type": "wiki"},
    )


def _download_github_docs() -> list[Document]:
    """Download the FreeCAD-documentation repo zip and extract markdown files."""
    print("Downloading FreeCAD-documentation from GitHub...")
    try:
        resp = requests.get(GITHUB_ZIP_URL, timeout=60, stream=True)
        resp.raise_for_status()
    except Exception as e:
        print(f"  FAILED: {e}")
        return []

    docs = []
    zf = zipfile.ZipFile(io.BytesIO(resp.content))
    for name in zf.namelist():
        # Only process .md files in the included sub-folders
        parts = Path(name).parts
        if len(parts) < 2:
            continue
        subdir = parts[1].lower()
        if not any(subdir.startswith(d) for d in GITHUB_INCLUDE_DIRS):
            continue
        if not name.endswith(".md"):
            continue

        text = zf.read(name).decode("utf-8", errors="replace").strip()
        if len(text) < 100:
            continue

        title = Path(name).stem.replace("_", " ").replace("-", " ").title()
        docs.append(
            Document(
                page_content=text,
                metadata={"source": f"github:{name}", "title": title, "type": "github"},
            )
        )
        print(f"  + {name}")

    return docs


def _chunk(docs: list[Document]) -> list[Document]:
    splitter = RecursiveCharacterTextSplitter(
        chunk_size=CHUNK_SIZE,
        chunk_overlap=CHUNK_OVERLAP,
        separators=["\n\n", "\n", " ", ""],
    )
    return splitter.split_documents(docs)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest FreeCAD docs into ChromaDB")
    parser.add_argument("--wiki-only", action="store_true")
    parser.add_argument("--github-only", action="store_true")
    parser.add_argument("--clear", action="store_true", help="Wipe ChromaDB before ingesting")
    args = parser.parse_args()

    print("Loading embedding model (downloads once on first run)...")
    embeddings = HuggingFaceEmbeddings(model_name=EMBED_MODEL)

    vectorstore = Chroma(
        collection_name=COLLECTION_NAME,
        embedding_function=embeddings,
        persist_directory=CHROMA_PATH,
    )

    if args.clear:
        print("Clearing existing ChromaDB collection...")
        vectorstore._collection.delete(where={"source": {"$ne": ""}})

    raw_docs: list[Document] = []

    if not args.github_only:
        print(f"\nScraping {len(WIKI_PAGES)} FreeCAD wiki pages...")
        for url in WIKI_PAGES:
            doc = _scrape_wiki_page(url)
            if doc:
                raw_docs.append(doc)
                print(f"  + {doc.metadata['title']}")

    if not args.wiki_only:
        github_docs = _download_github_docs()
        raw_docs.extend(github_docs)

    if not raw_docs:
        print("\nNo documents collected. Exiting.")
        sys.exit(1)

    print(f"\nChunking {len(raw_docs)} documents...")
    chunks = _chunk(raw_docs)
    print(f"  -> {len(chunks)} chunks")

    print("Embedding and storing in ChromaDB...")
    # Add in batches to avoid memory spikes
    batch_size = 100
    for i in range(0, len(chunks), batch_size):
        batch = chunks[i : i + batch_size]
        vectorstore.add_documents(batch)
        print(f"  {min(i + batch_size, len(chunks))}/{len(chunks)}")

    total = vectorstore._collection.count()
    print(f"\nDone. ChromaDB now contains {total} chunks.")


if __name__ == "__main__":
    main()
