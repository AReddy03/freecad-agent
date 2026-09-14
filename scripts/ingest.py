"""
FreeCAD documentation ingestion pipeline.

Sources:
  1. FreeCAD wiki  — key pages scraped via HTTP
  2. FreeCAD-documentation GitHub repo — downloaded as a zip and extracted

Re-running is safe: chunks have stable IDs, so existing ones are overwritten.

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

sys.path.insert(0, str(Path(__file__).parent.parent))

import requests
from langchain_core.documents import Document

from agent.vectorstore import DOCS_CHROMA_PATH, DOCS_COLLECTION
from scripts.ingest_common import index_documents, open_vectorstore, scrape_pages

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

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

def _download_github_docs() -> list[Document]:
    """Download the FreeCAD-documentation repo zip and extract markdown files."""
    print("Downloading FreeCAD-documentation from GitHub...")
    try:
        resp = requests.get(GITHUB_ZIP_URL, timeout=60)
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


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest FreeCAD docs into ChromaDB")
    parser.add_argument("--wiki-only", action="store_true")
    parser.add_argument("--github-only", action="store_true")
    parser.add_argument("--clear", action="store_true", help="Wipe ChromaDB before ingesting")
    args = parser.parse_args()

    vectorstore = open_vectorstore(DOCS_COLLECTION, DOCS_CHROMA_PATH, clear=args.clear)

    raw_docs: list[Document] = []

    if not args.github_only:
        print(f"\nScraping {len(WIKI_PAGES)} FreeCAD wiki pages...")
        raw_docs.extend(scrape_pages(WIKI_PAGES, source_type="wiki"))

    if not args.wiki_only:
        raw_docs.extend(_download_github_docs())

    if not raw_docs:
        print("\nNo documents collected. Exiting.")
        sys.exit(1)

    total = index_documents(vectorstore, raw_docs)
    print(f"\nDone. ChromaDB now contains {total} chunks.")


if __name__ == "__main__":
    main()
