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
import podcast

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env", override=True)

# ---------------------------------------------------------------------------
# Configuration — override with environment variables for security
# ---------------------------------------------------------------------------
DISCORD_BOT_TOKEN = os.environ.get("DISCORD_BOT_TOKEN", "")
CHANNEL_ID = os.environ.get("DISCORD_CHANNEL_ID", "")
DISCORD_USER_ID = os.environ.get("DISCORD_USER_ID", "")

# How many messages to fetch (max 100 per Discord API call)
MESSAGE_LIMIT = 100

# Max characters of page content to send to the model
CONTENT_MAX_CHARS = 8_000

# Characters of raw transcript shown in digest for quality verification (step 3)
TRANSCRIPT_PREVIEW_CHARS = 2_000

DIGESTS_DIR = BASE_DIR / "digests"
DB_FILE = BASE_DIR / "links.db"

# ---------------------------------------------------------------------------
# Discord helpers
# ---------------------------------------------------------------------------
DISCORD_API = "https://discord.com/api/v10"


def discord_headers() -> dict:
    return {"Authorization": f"Bot {DISCORD_BOT_TOKEN}"}


def open_dm_channel(user_id: str) -> str:
    """Create or retrieve a DM channel with user_id. Returns channel_id."""
    resp = requests.post(
        f"{DISCORD_API}/users/@me/channels",
        headers=discord_headers(),
        json={"recipient_id": user_id},
        timeout=10,
    )
    if not resp.ok:
        try:
            detail = resp.json()
            code = detail.get("code", "?")
            msg  = detail.get("message", resp.text)
        except Exception:
            code, msg = "?", resp.text
        if code == 50007:
            raise RuntimeError(
                f"Discord error {code}: {msg}\n"
                "Fix: Discord → Settings → Privacy & Safety → "
                "turn ON 'Allow direct messages from server members'."
            )
        if code == 10013:
            raise RuntimeError(
                f"Discord error {code}: {msg}\n"
                "Fix: check DISCORD_USER_ID in .env — enable Developer Mode in Discord, "
                "right-click your username → Copy User ID."
            )
        if code == 50035:
            field_errors = detail.get("errors", {})
            raise RuntimeError(
                f"Discord error {code}: {msg}\n"
                f"Field errors: {field_errors}\n"
                "Fix: DISCORD_USER_ID in .env must be a numeric snowflake ID, not a username.\n"
                "How to get it: Discord → Settings → Advanced → Developer Mode ON, "
                "then right-click your own username → Copy User ID."
            )
        raise RuntimeError(f"Discord error {code}: {msg}")
    return resp.json()["id"]


def send_dm_digest(entries: list[dict], date: str) -> None:
    """Send the digest to DISCORD_USER_ID as DM messages (split at 2000-char limit)."""
    if not DISCORD_USER_ID:
        return

    try:
        channel_id = open_dm_channel(DISCORD_USER_ID)
    except Exception as exc:
        print(f"  [DM] Could not open DM channel: {exc}", file=sys.stderr)
        return

    msg_url = f"{DISCORD_API}/channels/{channel_id}/messages"

    def post(text: str) -> None:
        requests.post(msg_url, headers=discord_headers(), json={"content": text}, timeout=10)

    successful = sum(1 for e in entries if not e.get("error"))
    failed = len(entries) - successful
    header = f"**\U0001f4ec My Link Inbox — {date}**\n{successful} summarized"
    if failed:
        header += f", {failed} failed"
    post(header)

    chunk = ""
    for i, entry in enumerate(entries, 1):
        if entry.get("error"):
            block = f"**{i}.** <{entry['url']}>\n> ⚠️ {entry['error']}\n\n"
        else:
            provenance = ""
            if entry.get("author"):
                provenance = f"*{entry['author']} · {entry.get('timestamp', '')}*\n\n"
            block = (
                f"**{i}.** <{entry['url']}>\n"
                f"{provenance}"
                f"{entry.get('summary', '')}\n\n"
                "─────────────\n\n"
            )

        if len(chunk) + len(block) > 1900:
            if chunk.strip():
                post(chunk.strip())
            chunk = block
        else:
            chunk += block

    if chunk.strip():
        post(chunk.strip())

    print(f"  DM sent ({successful} summarized, {failed} failed)")


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

def _format_entry(entry: dict, index: int) -> list[str]:
    if entry.get("type") == "podcast":
        lines = [f"## {index}. \U0001f399️ PODCAST — [{entry['url']}]({entry['url']})", ""]
        if entry.get("author"):
            lines += [f"*Shared by **{entry['author']}** on {entry['timestamp']}*", ""]
        if entry.get("error"):
            lines.append(f"> **Could not process podcast:** {entry['error']}")
        else:
            meta_parts = []
            if entry.get("duration_mins"):
                meta_parts.append(f"~{entry['duration_mins']} min episode")
            if entry.get("word_count"):
                meta_parts.append(f"{entry['word_count']:,} words transcribed")
            if meta_parts:
                lines += [f"**{' | '.join(meta_parts)}**", ""]
            if entry.get("transcript_preview"):
                lines += [
                    "*Raw transcript — verify quality before enabling summarization:*",
                    "",
                    entry["transcript_preview"],
                    "...",
                    "",
                ]
        lines += ["", "---", ""]
        return lines

    lines = [f"## {index}. [{entry['url']}]({entry['url']})", ""]
    if entry.get("author"):
        lines += [f"*Shared by **{entry['author']}** on {entry['timestamp']}*", ""]
    if entry.get("error"):
        lines.append(f"> **Could not fetch content:** {entry['error']}")
    else:
        lines.append(entry["summary"])
    lines += ["", "---", ""]
    return lines


def write_digest(entries: list[dict], output_path, start_index: int = 1) -> None:
    if start_index > 1:
        # Append to existing file: update the count in the header, add new entries
        text = Path(output_path).read_text(encoding="utf-8")
        total = start_index - 1 + len(entries)
        text = re.sub(r"\*\*Links processed:\*\* \d+", f"**Links processed:** {total}", text)
        new_lines: list[str] = []
        for i, entry in enumerate(entries, start_index):
            new_lines.extend(_format_entry(entry, i))
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(text.rstrip() + "\n\n" + "\n".join(new_lines))
        return

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [
        "# Discord Link Digest", "",
        f"**Channel:** `{CHANNEL_ID}`  ",
        f"**Generated:** {now}  ",
        f"**Links processed:** {len(entries)}",
        "", "---", "",
    ]
    for i, entry in enumerate(entries, 1):
        lines.extend(_format_entry(entry, i))
    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    if not DISCORD_BOT_TOKEN:
        sys.exit("Error: DISCORD_BOT_TOKEN environment variable is not set.")
    if not CHANNEL_ID:
        sys.exit("Error: DISCORD_CHANNEL_ID environment variable is not set.")

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
        source = urllib.parse.urlparse(url).netloc
        entry = {"url": url, **meta}
        summary = None
        title = None

        if podcast.is_podcast_url(url):
            try:
                transcript, title, duration_mins = podcast.fetch_podcast(url)
                if transcript:
                    entry["type"] = "podcast"
                    entry["duration_mins"] = duration_mins
                    entry["transcript_preview"] = transcript[:TRANSCRIPT_PREVIEW_CHARS]
                    entry["word_count"] = len(transcript.split())
                    # summary stays None — user verifies transcript quality before step 4
                else:
                    entry["error"] = "Could not download or transcribe podcast audio."
            except Exception as exc:
                entry["error"] = f"Podcast processing failed: {exc}"
        else:
            content, title = fetch_page_text(url)
            if content:
                print(f"  Summarizing...")
                try:
                    summary = providers.summarize(url, content)
                    entry["summary"] = summary
                except Exception as exc:
                    entry["error"] = f"Summarization failed: {exc}"
            else:
                entry["error"] = "Could not retrieve page content."

        # Always save to DB — even on failure — so the URL won't be retried tomorrow
        db.save_link(
            DB_FILE,
            url=url,
            date_processed=today,
            source=source,
            title=title,
            summary=summary,
            author=meta.get("author"),
            discord_ts=meta.get("timestamp"),
        )
        entries.append(entry)

    os.makedirs(DIGESTS_DIR, exist_ok=True)
    output_path = DIGESTS_DIR / f"digest-{today}.md"
    start_index = 1
    if output_path.exists():
        existing_text = output_path.read_text(encoding="utf-8")
        start_index = len(re.findall(r"^## \d+\.", existing_text, re.MULTILINE)) + 1
    write_digest(entries, output_path, start_index=start_index)
    print(f"\nDigest saved to: {output_path}")
    send_dm_digest(entries, today)


if __name__ == "__main__":
    main()
