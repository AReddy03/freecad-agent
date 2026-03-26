"""
Health check — verifies all components are reachable before starting the agent.

Usage:
    python scripts/test_connection.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


def check(label: str, fn):
    try:
        result = fn()
        print(f"  [OK]  {label}" + (f" — {result}" if result else ""))
        return True
    except Exception as e:
        print(f"  [FAIL] {label}: {e}")
        return False


def test_freecad(host, port):
    from agent.freecad_client import FreeCADClient
    c = FreeCADClient(host=host, port=port)
    c.connect()
    objs = c.list_objects()
    c.disconnect()
    return f"{len(objs)} object(s) in document"


def test_llm(config):
    from agent.llm import get_llm
    llm = get_llm(config)
    resp = llm.invoke("Reply with the single word: OK")
    return resp.content.strip()[:40]


def test_chromadb():
    from agent.rag import collection_size
    n = collection_size()
    if n == 0:
        raise RuntimeError("Collection is empty — run: python scripts/ingest.py")
    return f"{n} chunks"


def test_ollama():
    from agent.llm import is_ollama_running, list_ollama_models
    if not is_ollama_running():
        raise RuntimeError("Ollama is not running")
    models = list_ollama_models()
    return f"{len(models)} model(s): {', '.join(models[:3])}"


def main():
    from agent.config import load_config
    config = load_config()

    print("\nFreeCAD Agent - connection check\n")
    results = []

    results.append(
        check("FreeCAD RPC server", lambda: test_freecad(config.freecad_host, config.freecad_port))
    )

    if config.provider == "ollama":
        results.append(check("Ollama", test_ollama))
    else:
        if not config.api_key:
            print(f"  [SKIP] LLM ({config.provider}) — no API key configured")
            print("         Open the Settings panel and enter your API key.")
        else:
            results.append(check(f"LLM ({config.provider}/{config.model})", lambda: test_llm(config)))

    results.append(check("ChromaDB (RAG)", test_chromadb))

    print()
    if all(results):
        print("All checks passed. Run the agent with:")
        print("  streamlit run ui/app.py")
    else:
        print("Some checks failed. Fix the issues above before starting the agent.")
        sys.exit(1)


if __name__ == "__main__":
    main()
