"""RAG search CLI for discord_digest.

Usage:
    python search.py "what have I saved about AI agents?"
    python search.py "summarize everything I read about the economy in May"
    python search.py "AI topics" --top-k 20

Requires Ollama running locally with OLLAMA_EMBED_MODEL available.
The all-minilm model is used by default (already pulled if you followed setup).
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv
import chromadb
from chromadb.utils.embedding_functions import OllamaEmbeddingFunction
import db
import providers

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

DB_FILE = BASE_DIR / "links.db"
CHROMA_DIR = BASE_DIR / ".chromadb"
COLLECTION_NAME = "link_summaries"
TOP_K = 10

OLLAMA_BASE_URL = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
OLLAMA_EMBED_MODEL = os.environ.get("OLLAMA_EMBED_MODEL", "all-minilm")

# all-minilm has a ~256 token context window (~1000 chars). Truncate before embedding.
MAX_EMBED_CHARS = 900


def get_collection():
    ef = OllamaEmbeddingFunction(
        url=f"{OLLAMA_BASE_URL}/api/embeddings",
        model_name=OLLAMA_EMBED_MODEL,
    )
    client = chromadb.PersistentClient(path=str(CHROMA_DIR))
    return client.get_or_create_collection(name=COLLECTION_NAME, embedding_function=ef)


def sync_index(collection) -> int:
    """Upsert any summaries from SQLite not yet in ChromaDB. Returns count added."""
    summaries = db.get_all_summaries(DB_FILE)
    if not summaries:
        return 0
    existing = set(collection.get()["ids"])
    new_rows = [r for r in summaries if r["url"] not in existing]
    if new_rows:
        collection.upsert(
            ids=[r["url"] for r in new_rows],
            documents=[r["summary"][:MAX_EMBED_CHARS] for r in new_rows],
            metadatas=[{
                "url": r["url"],
                "title": r["title"] or "",
                "source": r["source"] or "",
                "date": r["date_processed"],
            } for r in new_rows],
        )
    return len(new_rows)


def build_context(items: list[dict]) -> str:
    """Build context string from a list of {doc, meta} dicts."""
    parts = []
    for i, item in enumerate(items, 1):
        doc = item["doc"]
        meta = item["meta"]
        title = meta.get("title") or meta.get("url")
        source = meta.get("source", "")
        date = meta.get("date", "")
        url = meta.get("url", "")
        parts.append(f"{i}. {title} ({source}, {date})\n   URL: {url}\n   {doc}")
    return "\n\n".join(parts)


def print_reference_table(items: list[dict]) -> None:
    """Print a numbered URL list so users can look up any #N cited in the answer."""
    print(f"References ({len(items)} articles):")
    for i, item in enumerate(items, 1):
        meta = item["meta"]
        url = meta.get("url", "")
        source = meta.get("source", "") or url
        date = meta.get("date", "")
        title = meta.get("title") or ""
        label = (title[:57] + "…") if len(title) > 60 else title
        print(f"  #{i:<4} {date}  {source:<30}  {url}")
    print()


def merge_results(semantic_results: dict, keyword_rows: list[dict]) -> list[dict]:
    """Merge semantic and keyword results, deduplicated by URL. Semantic first."""
    seen = set()
    merged = []
    # Semantic results first — already ranked by relevance
    for doc, meta in zip(
        semantic_results["documents"][0], semantic_results["metadatas"][0]
    ):
        url = meta["url"]
        if url not in seen:
            seen.add(url)
            merged.append({"doc": doc, "meta": meta})
    # Keyword-only matches appended after
    for row in keyword_rows:
        url = row["url"]
        if url not in seen:
            seen.add(url)
            merged.append({
                "doc": row["summary"],
                "meta": {
                    "url": row["url"],
                    "title": row.get("title") or "",
                    "source": row.get("source") or "",
                    "date": row.get("date_processed") or "",
                },
            })
    return merged


def main():
    if len(sys.argv) < 2:
        sys.exit('Usage: python search.py "your question here" [--top-k N]')

    # Parse optional --top-k N flag
    args = sys.argv[1:]
    top_k = TOP_K
    if "--top-k" in args:
        idx = args.index("--top-k")
        try:
            top_k = int(args[idx + 1])
            args = args[:idx] + args[idx + 2:]  # remove flag + value
        except (IndexError, ValueError):
            sys.exit("Usage: --top-k must be followed by a number, e.g. --top-k 20")

    question = " ".join(args)
    if not question:
        sys.exit('Usage: python search.py "your question here" [--top-k N]')

    print("Loading index...")
    try:
        collection = get_collection()
    except Exception as exc:
        sys.exit(
            f"Could not connect to Ollama for embeddings: {exc}\n"
            "Make sure Ollama is running (ollama serve) and "
            f"'{OLLAMA_EMBED_MODEL}' is available."
        )

    added = sync_index(collection)
    if added:
        print(f"  Indexed {added} new article(s).")

    total = collection.count()
    if total == 0:
        sys.exit("No summaries indexed yet. Run discord_digest.py first to build your digest.")

    print(f"  Searching {total} article(s)...\n")
    semantic_results = collection.query(query_texts=[question], n_results=min(top_k, total))
    keyword_rows = db.keyword_search(DB_FILE, question)

    items = merge_results(semantic_results, keyword_rows)
    sem_count = len(semantic_results["documents"][0])
    kw_only = len(items) - sem_count
    print(f"  Semantic: {sem_count} results, keyword: {len(keyword_rows)} matches "
          f"({kw_only} unique additions)\n")

    if not items:
        print("No relevant articles found.")
        return

    print_reference_table(items)
    context = build_context(items)
    try:
        response = providers.answer(question, context)
    except Exception as exc:
        sys.exit(f"Error generating answer: {exc}")
    print(response)


if __name__ == "__main__":
    main()
