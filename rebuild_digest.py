"""Rebuild a digest markdown file from the database and send the DM.

Reads all entries for the given date from links.db, rewrites the markdown
file from scratch, and sends the full digest as a Discord DM.

Usage:
    python rebuild_digest.py                # today
    python rebuild_digest.py 2026-06-19     # specific date
"""

import sys
import datetime
import sqlite3
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

# Import after dotenv so module-level env vars (DISCORD_USER_ID etc.) are set
from discord_digest import write_digest, send_dm_digest, DIGESTS_DIR, DB_FILE


def get_entries_for_date(date: str) -> list[dict]:
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT url, summary, author, discord_ts "
        "FROM links WHERE date_processed = ? ORDER BY rowid",
        (date,),
    ).fetchall()
    conn.close()

    entries = []
    for row in rows:
        entry = {
            "url": row["url"],
            "author": row["author"] or "",
            "timestamp": row["discord_ts"] or "",
        }
        if row["summary"]:
            entry["summary"] = row["summary"]
        else:
            entry["error"] = "Could not retrieve page content."
        entries.append(entry)
    return entries


def main() -> None:
    date = sys.argv[1] if len(sys.argv) > 1 else datetime.date.today().strftime("%Y-%m-%d")

    entries = get_entries_for_date(date)
    if not entries:
        print(f"No entries found in DB for {date}.")
        return

    summarized = sum(1 for e in entries if "summary" in e)
    failed = len(entries) - summarized
    print(f"Found {len(entries)} entries for {date} ({summarized} summarized, {failed} failed).")

    output_path = DIGESTS_DIR / f"digest-{date}.md"
    # start_index=1 forces a full rewrite (not append)
    write_digest(entries, output_path, start_index=1)
    print(f"Rebuilt: {output_path}")

    send_dm_digest(entries, date)


if __name__ == "__main__":
    main()
