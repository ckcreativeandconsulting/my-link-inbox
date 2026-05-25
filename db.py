"""SQLite persistence layer for discord_digest."""

import sqlite3
from pathlib import Path


def _connect(db_path: Path):
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: Path) -> None:
    """Create the links table if it doesn't exist."""
    with _connect(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS links (
                id             INTEGER PRIMARY KEY AUTOINCREMENT,
                url            TEXT UNIQUE NOT NULL,
                date_processed TEXT NOT NULL,
                source         TEXT,
                title          TEXT,
                summary        TEXT,
                author         TEXT,
                discord_ts     TEXT
            )
        """)


def migrate_from_json(db_path: Path, json_path: Path) -> int:
    """One-time import of processed_links.json into SQLite. Returns rows inserted."""
    import json
    if not json_path.exists():
        return 0
    with open(json_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    inserted = 0
    with _connect(db_path) as conn:
        for url, date in data.items():
            try:
                conn.execute(
                    "INSERT OR IGNORE INTO links (url, date_processed) VALUES (?, ?)",
                    (url, date),
                )
                inserted += conn.execute("SELECT changes()").fetchone()[0]
            except Exception:
                pass
    return inserted


def is_processed(db_path: Path, url: str) -> bool:
    with _connect(db_path) as conn:
        row = conn.execute("SELECT 1 FROM links WHERE url = ?", (url,)).fetchone()
        return row is not None


def save_link(
    db_path: Path,
    *,
    url: str,
    date_processed: str,
    source: str | None,
    title: str | None,
    summary: str | None,
    author: str | None,
    discord_ts: str | None,
) -> None:
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO links
                (url, date_processed, source, title, summary, author, discord_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (url, date_processed, source, title, summary, author, discord_ts),
        )


def backfill_link(
    db_path: Path,
    *,
    url: str,
    date_processed: str,
    source: str | None,
    title: str | None,
    summary: str | None,
    author: str | None,
    discord_ts: str | None,
) -> bool:
    """Insert or fill-in a link from a digest file. Returns True if data was written.

    - New URL: inserts the row.
    - Existing URL with no summary: fills in summary and any other NULL fields.
    - Existing URL already has a summary: no-op (live data wins). Returns False.
    """
    with _connect(db_path) as conn:
        conn.execute(
            """
            INSERT INTO links
                (url, date_processed, source, title, summary, author, discord_ts)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(url) DO UPDATE SET
                summary    = EXCLUDED.summary,
                source     = COALESCE(links.source,     EXCLUDED.source),
                title      = COALESCE(links.title,      EXCLUDED.title),
                author     = COALESCE(links.author,     EXCLUDED.author),
                discord_ts = COALESCE(links.discord_ts, EXCLUDED.discord_ts)
            WHERE links.summary IS NULL
            """,
            (url, date_processed, source, title, summary, author, discord_ts),
        )
        # changes() == 1 if a row was inserted or the DO UPDATE SET fired
        # changes() == 0 if the row already had a summary (WHERE clause false)
        return conn.execute("SELECT changes()").fetchone()[0] == 1


def get_all_summaries(db_path: Path) -> list[dict]:
    """Return all rows that have a summary — used by RAG search."""
    with _connect(db_path) as conn:
        rows = conn.execute(
            "SELECT url, title, source, date_processed, summary FROM links WHERE summary IS NOT NULL"
        ).fetchall()
        return [dict(r) for r in rows]


_STOP_WORDS = {
    "what", "have", "saved", "about", "the", "all", "and", "etc", "for", "that",
    "this", "are", "was", "with", "from", "has", "had", "but", "not", "you",
    "will", "may", "can", "than", "more", "its", "how", "who", "why", "when",
    "any", "been", "were", "did", "our", "also", "into", "some", "them", "they",
    "mention", "articles", "just", "like", "tell", "show", "find", "get",
}


def keyword_search(db_path: Path, query: str) -> list[dict]:
    """Return all rows whose summary or title contains any significant word in query."""
    import re
    words = re.findall(r"[A-Za-z0-9]+", query)
    words = [w for w in words if len(w) >= 2 and w.lower() not in _STOP_WORDS]
    if not words:
        return []
    clauses = [
        "(LOWER(summary) LIKE ? OR LOWER(COALESCE(title,'')) LIKE ?)"
        for _ in words
    ]
    params = []
    for w in words:
        params.append(f"%{w.lower()}%")
        params.append(f"%{w.lower()}%")
    where = " OR ".join(clauses)
    with _connect(db_path) as conn:
        rows = conn.execute(
            f"SELECT url, title, source, date_processed, summary FROM links "
            f"WHERE summary IS NOT NULL AND ({where})",
            params,
        ).fetchall()
        return [dict(r) for r in rows]
