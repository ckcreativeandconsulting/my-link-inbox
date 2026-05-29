"""Retry failed summarizations in a digest markdown file.

Finds every entry with a "Could not fetch content" error block,
re-fetches the page, re-summarizes via the configured AI provider,
saves to SQLite, and rewrites the markdown file in place.

Usage:
    python retry.py                            # retries today's digest
    python retry.py 2026-05-28                # retries a specific date
    python retry.py digests/digest-2026-05-28.md  # explicit path
"""

import sys
import re
import datetime
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
import db
import providers
from discord_digest import fetch_page_text, write_digest

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

DB_FILE     = BASE_DIR / "links.db"
DIGESTS_DIR = BASE_DIR / "digests"

RE_ENTRY_HEADER = re.compile(r"^## \d+\. \[.+?\]\((.+?)\)", re.MULTILINE)
RE_PROVENANCE   = re.compile(r"\*Shared by \*\*(.+?)\*\* on (.+?)\*")
RE_MD_HEADING   = re.compile(r"^## .+", re.MULTILINE)
ERROR_MARKER    = "> **Could not fetch content:**"


def parse_all_entries(md_path: Path) -> list[dict]:
    """Parse every entry from a digest file, flagging failed ones for retry."""
    text   = md_path.read_text(encoding="utf-8")
    blocks = text.split("\n---\n")
    entries = []
    for block in blocks[1:]:   # first block is the file header
        block = block.strip()
        if not block:
            continue
        url_match = RE_ENTRY_HEADER.search(block)
        if not url_match:
            continue
        url       = url_match.group(1)
        prov      = RE_PROVENANCE.search(block)
        author    = prov.group(1) if prov else None
        timestamp = prov.group(2) if prov else None

        if ERROR_MARKER in block:
            entries.append({
                "url": url, "author": author, "timestamp": timestamp,
                "summary": None, "error": "retry", "_needs_retry": True,
            })
        else:
            after   = block[prov.end():] if prov else block[url_match.end():]
            summary = RE_MD_HEADING.sub("", after).strip()
            summary = re.sub(r"\n{3,}", "\n\n", summary).strip()
            entries.append({
                "url": url, "author": author, "timestamp": timestamp,
                "summary": summary, "error": None, "_needs_retry": False,
            })
    return entries


def resolve_path(arg: str | None) -> Path:
    """Turn a date string, explicit path, or None (today) into a digest Path."""
    if arg is None:
        date = datetime.date.today().strftime("%Y-%m-%d")
    elif re.match(r"^\d{4}-\d{2}-\d{2}$", arg):
        date = arg
    else:
        p = Path(arg)
        if p.exists():
            return p
        sys.exit(f"File not found: {arg}")
    p = DIGESTS_DIR / f"digest-{date}.md"
    if not p.exists():
        sys.exit(f"Digest file not found: {p}")
    return p


def main():
    arg     = sys.argv[1] if len(sys.argv) > 1 else None
    md_path = resolve_path(arg)
    date_processed = md_path.stem.replace("digest-", "")

    print(f"Reading {md_path.name}...")
    entries  = parse_all_entries(md_path)
    to_retry = [e for e in entries if e["_needs_retry"]]

    if not to_retry:
        print("No failed entries found — nothing to do.")
        return

    print(f"  {len(to_retry)} failed entries to retry "
          f"({len(entries) - len(to_retry)} already succeeded).\n")

    try:
        providers.ensure_ollama()
    except RuntimeError as exc:
        sys.exit(f"Ollama setup failed: {exc}")

    retried = fixed = 0
    for entry in entries:
        if not entry["_needs_retry"]:
            continue
        retried += 1
        url = entry["url"]
        print(f"Retrying: {url}")
        content, title = fetch_page_text(url)
        source = urllib.parse.urlparse(url).netloc
        if content:
            try:
                summary = providers.summarize(url, content)
                db.save_link(
                    DB_FILE,
                    url=url,
                    date_processed=date_processed,
                    source=source,
                    title=title,
                    summary=summary,
                    author=entry.get("author"),
                    discord_ts=entry.get("timestamp"),
                )
                entry["summary"] = summary
                entry["error"]   = None
                fixed += 1
                print("  summarized.")
            except Exception as exc:
                entry["error"] = f"Summarization failed: {exc}"
                print(f"  failed: {exc}")
        else:
            entry["error"] = "Could not retrieve page content."
            print("  failed: could not fetch page.")

    write_digest(entries, md_path)
    print(f"\nDone. {fixed}/{retried} entries fixed. Digest rewritten: {md_path.name}")


if __name__ == "__main__":
    main()
