"""Backfill digest markdown files into SQLite for RAG search.

Parses all digest-YYYY-MM-DD.md files in the digests/ folder and inserts
any missing rows into links.db using INSERT OR IGNORE (existing rows are
never overwritten).

Usage:
    python backfill.py
"""

import re
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
import db

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

DB_FILE = BASE_DIR / "links.db"
DIGESTS_DIR = BASE_DIR / "digests"

# Regex patterns
RE_ENTRY_HEADER = re.compile(r"^## \d+\. \[.+?\]\((.+?)\)", re.MULTILINE)
RE_PROVENANCE = re.compile(r"\*Shared by \*\*(.+?)\*\* on (.+?)\*")
RE_MD_HEADING = re.compile(r"^## .+", re.MULTILINE)
ERROR_MARKER = "> **Could not fetch content:**"


def parse_digest(md_path: Path, date_processed: str) -> list[dict]:
    """Parse one digest markdown file. Returns list of entry dicts."""
    text = md_path.read_text(encoding="utf-8")
    # Split into blocks; the first block is the file header (before first ---)
    blocks = text.split("\n---\n")
    entries = []
    for block in blocks[1:]:  # skip header block
        block = block.strip()
        if not block:
            continue
        # Find URL
        url_match = RE_ENTRY_HEADER.search(block)
        if not url_match:
            continue
        url = url_match.group(1)
        # Error entries: record URL in DB with summary=None so they aren't retried
        if ERROR_MARKER in block:
            prov_match = RE_PROVENANCE.search(block)
            author     = prov_match.group(1) if prov_match else None
            discord_ts = prov_match.group(2) if prov_match else None
            source     = urllib.parse.urlparse(url).netloc
            entries.append({
                "url": url,
                "date_processed": date_processed,
                "source": source,
                "title": None,
                "summary": None,
                "author": author,
                "discord_ts": discord_ts,
            })
            continue
        # Find provenance
        prov_match = RE_PROVENANCE.search(block)
        author = prov_match.group(1) if prov_match else None
        discord_ts = prov_match.group(2) if prov_match else None
        # Extract summary: text after provenance line, strip ## headings and blank edges
        if prov_match:
            after_prov = block[prov_match.end():]
        else:
            after_prov = block[url_match.end():]
        # Remove markdown headings (## Summary, ## Key takeaway, etc.)
        summary_text = RE_MD_HEADING.sub("", after_prov).strip()
        # Collapse runs of 3+ newlines to 2
        summary_text = re.sub(r"\n{3,}", "\n\n", summary_text).strip()
        if not summary_text:
            continue
        source = urllib.parse.urlparse(url).netloc
        entries.append({
            "url": url,
            "date_processed": date_processed,
            "source": source,
            "title": None,       # not stored in markdown
            "summary": summary_text,
            "author": author,
            "discord_ts": discord_ts,
        })
    return entries


def main():
    db.init_db(DB_FILE)
    md_files = sorted(DIGESTS_DIR.glob("digest-*.md"))
    if not md_files:
        print("No digest files found in", DIGESTS_DIR)
        return

    total_scanned = 0
    total_inserted = 0
    total_skipped_existing = 0

    for md_path in md_files:
        # Extract date from filename: "digest-2026-05-19" -> "2026-05-19"
        date_processed = md_path.stem.replace("digest-", "")
        entries = parse_digest(md_path, date_processed)
        total_scanned += len(entries)

        file_written = 0
        file_skipped = 0
        for entry in entries:
            written = db.backfill_link(DB_FILE, **entry)
            if written:
                file_written += 1
            else:
                file_skipped += 1

        total_inserted += file_written
        total_skipped_existing += file_skipped
        error_count = sum(1 for e in entries if e["summary"] is None)
        print(
            f"  {md_path.name}: {file_written} written "
            f"({error_count} fetch-error stubs), {file_skipped} already in DB"
        )

    print(
        f"\nDone. Scanned {total_scanned} entries across {len(md_files)} file(s): "
        f"{total_inserted} written, {total_skipped_existing} already in DB."
    )


if __name__ == "__main__":
    main()
