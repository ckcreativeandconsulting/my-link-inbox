"""
Discord channel digest: fetches messages, extracts URLs, summarizes via AI, saves markdown.

Dependencies:
    pip install requests beautifulsoup4 anthropic python-dotenv
    pip install openai   # only needed if AI_PROVIDER=openai

Usage:
    python discord_digest.py

Environment variables:
    DISCORD_BOT_TOKEN   - Discord bot token
    AI_PROVIDER         - anthropic (default) | openai | ollama
    ANTHROPIC_API_KEY   - required when AI_PROVIDER=anthropic
    OPENAI_API_KEY      - required when AI_PROVIDER=openai
"""

import os
import re
import sys
import json
import datetime
import urllib.parse
from pathlib import Path
from dotenv import load_dotenv
import requests
from bs4 import BeautifulSoup
import db
import providers

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

# ---------------------------------------------------------------------------
# Configuration — override with environment variables for security
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "1506358200385929438")

# How many messages to fetch (max 100 per Discord API call)
MESSAGE_LIMIT = 100

# Max characters of page content to send to the model
CONTENT_MAX_CHARS = 8_000

DIGESTS_DIR = BASE_DIR / "digests"
DB_FILE = BASE_DIR / "links.db"

# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------
DISCORD_API = "https://discord.com/api/v10"


def discord_headers() -> dict:
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


def fetch_messages(channel_id: str, limit: int = 100) -> list[dict]:
    """Fetch up to `limit` messages from a Discord channel."""
    url = f"{DISCORD_API}/channels/{channel_id}/messages"
    params = {"limit": min(limit, 100)}
    response = requests.get(url, headers=discord_headers(), params=params, timeout=15)
    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# URL extraction
# ---------------------------------------------------------------------------
URL_PATTERN = re.compile(
    r"https?://"
    r"(?:[A-Za-z0-9\-._~:/?#\[\]@!$&'()*+,;=%]+"
    r")"
)


def extract_urls(text: str) -> list[str]:
    return list(dict.fromkeys(URL_PATTERN.findall(text)))  # deduplicated, order-preserved


# ---------------------------------------------------------------------------
# Web content fetching
# ---------------------------------------------------------------------------
FETCH_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; DiscordDigestBot/1.0)"
    )
}


def fetch_page_text(url: str) -> tuple[str, str | None] | tuple[None, None]:
    """Fetch a URL and return (text, title). Both are None on failure."""
    try:
        resp = requests.get(url, headers=FETCH_HEADERS, timeout=15, allow_redirects=True)
        resp.raise_for_status()
        content_type = resp.headers.get("content-type", "")
        if "html" in content_type:
            soup = BeautifulSoup(resp.text, "html.parser")
            title_tag = soup.find("title")
            title = title_tag.get_text(strip=True) if title_tag else None
            # Remove script/style noise
            for tag in soup(["script", "style", "nav", "footer", "header"]):
                tag.decompose()
            text = soup.get_text(separator="\n", strip=True)
            return text[:CONTENT_MAX_CHARS], title
        elif "json" in content_type:
            text = json.dumps(resp.json(), indent=2)
        else:
            text = resp.text
        return text[:CONTENT_MAX_CHARS], None
    except Exception as exc:
        print(f"  [warn] Could not fetch {url}: {exc}", file=sys.stderr)
        return None, None


# ---------------------------------------------------------------------------
# Markdown digest writer
# ---------------------------------------------------------------------------

def write_digest(entries: list[dict], output_path: str) -> None:
    """
    entries: list of {url, summary, author, timestamp, error}
    """
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        f"# Discord Link Digest",
        f"",
        f"**Channel:** `{CHANNEL_ID}`  ",
        f"**Generated:** {now}  ",
        f"**Links processed:** {len(entries)}",
        f"",
        "---",
        "",
    ]

    for i, entry in enumerate(entries, 1):
        lines.append(f"## {i}. [{entry['url']}]({entry['url']})")
        lines.append(f"")
        if entry.get("author"):
            lines.append(f"*Shared by **{entry['author']}** on {entry['timestamp']}*")
            lines.append(f"")
        if entry.get("error"):
            lines.append(f"> **Could not fetch content:** {entry['error']}")
        else:
            lines.append(entry["summary"])
        lines.append(f"")
        lines.append("---")
        lines.append("")

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not DISCORD_BOT_TOKEN:
        sys.exit("Error: DISCORD_BOT_TOKEN environment variable is not set.")

    db.init_db(DB_FILE)
    migrated = db.migrate_from_json(DB_FILE, BASE_DIR / "processed_links.json")
    if migrated:
        print(f"  Migrated {migrated} link(s) from processed_links.json to SQLite.")

    try:
        providers.ensure_ollama()
    except RuntimeError as exc:
        sys.exit(f"Ollama setup failed: {exc}")

    print(f"Fetching messages from channel {CHANNEL_ID}...")
    try:
        messages = fetch_messages(CHANNEL_ID, MESSAGE_LIMIT)
    except requests.HTTPError as exc:
        sys.exit(f"Discord API error: {exc}\nCheck your bot token and that the bot has read permissions.")

    if not messages:
        sys.exit("No messages found in channel.")

    print(f"  {len(messages)} messages retrieved.")

    # Collect unique URLs with provenance
    url_meta: dict[str, dict] = {}  # url -> {author, timestamp}
    for msg in messages:
        urls = extract_urls(msg.get("content", ""))
        author = msg.get("author", {}).get("username", "unknown")
        ts_raw = msg.get("timestamp", "")
        ts = ts_raw[:19].replace("T", " ") if ts_raw else ""
        for url in urls:
            if url not in url_meta:
                url_meta[url] = {"author": author, "timestamp": ts}

    if not url_meta:
        sys.exit("No URLs found in the fetched messages.")

    print(f"  {len(url_meta)} unique URL(s) found.")

    url_meta = {u: m for u, m in url_meta.items() if not db.is_processed(DB_FILE, u)}
    if not url_meta:
        sys.exit("No new links to process — all have been summarized before.")
    print(f"  {len(url_meta)} new (unprocessed) URL(s) to summarize.")

    today = datetime.date.today().strftime("%Y-%m-%d")
    entries: list[dict] = []

    for url, meta in url_meta.items():
        print(f"Processing: {url}")
        content, title = fetch_page_text(url)
        source = urllib.parse.urlparse(url).netloc
        entry = {"url": url, **meta}
        if content:
            print(f"  Summarizing...")
            try:
                entry["summary"] = providers.summarize(url, content)
                db.save_link(
                    DB_FILE,
                    url=url,
                    date_processed=today,
                    source=source,
                    title=title,
                    summary=entry["summary"],
                    author=meta.get("author"),
                    discord_ts=meta.get("timestamp"),
                )
            except Exception as exc:
                entry["error"] = f"Summarization failed: {exc}"
        else:
            entry["error"] = "Could not retrieve page content."
        entries.append(entry)

    os.makedirs(DIGESTS_DIR, exist_ok=True)
    output_path = DIGESTS_DIR / f"digest-{today}.md"
    write_digest(entries, output_path)
    print(f"\nDigest saved to: {output_path}")


if __name__ == "__main__":
    main()
