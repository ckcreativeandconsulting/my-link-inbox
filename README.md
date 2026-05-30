# MyLinkInbox

> Automatically summarizes links shared in a Discord channel, builds searchable daily digests, and lets you ask natural-language questions across your entire reading history.

---

## What it does

A Discord channel I'm in shares 30–50 links a day — articles, newsletters, and long reads. They disappear into the scroll. This tool fixes that.

Each time you run it:

1. **Fetches** the last 100 messages from a Discord channel and extracts every URL
2. **Scrapes** each page for its text content
3. **Summarizes** it in 3–5 sentences using the AI provider of your choice (Claude, GPT, or a local Ollama model)
4. **Saves** a dated Markdown digest file and persists everything to SQLite
5. **Indexes** summaries into ChromaDB so you can search them later

A companion CLI lets you query everything you've saved:

```
python search.py "what did I read about AI agents last week?"
python search.py "economy articles" --top-k 20
```

The search combines semantic similarity (ChromaDB vectors) and keyword matching (SQLite `LIKE`) so you get both conceptual relevance and exact-term recall.

---

## Why I built it

I was losing interesting articles to the Discord firehose and forgetting things I'd actually wanted to read. I wanted a personal knowledge base that:

- Required **zero manual effort** to populate — it reads from a channel I'm already in
- Let me **search by meaning**, not just keywords
- Worked with **local AI** so I could run it free after setup
- Gave me **full data ownership** — everything lives in local files I control

It's now a daily driver. I run it each morning, and `search.py` has replaced my "I know I read something about X" memory.

---

## Tech stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.11+ |
| Persistence | SQLite (summaries + metadata), ChromaDB (vector index) |
| Embeddings | Ollama `all-minilm` — local, 45 MB, runs on CPU |
| AI providers | Anthropic Claude · OpenAI GPT · Ollama local LLMs |
| Web scraping | `requests` + `BeautifulSoup` |
| Discord | REST API v10 via `requests` (no Discord SDK needed) |

Switching AI providers is a single line in `.env` — no code changes.

---

## Setup

### Prerequisites

- Python 3.11+
- A Discord bot token with **Message Read** permission in the target channel
- One of: an Anthropic API key, OpenAI API key, or [Ollama](https://ollama.ai) running locally

### Install

```bash
git clone https://github.com/your-username/MyLinkInbox
cd MyLinkInbox
pip install -r requirements.txt
```

### Configure

```bash
cp .env.example .env
# Edit .env — fill in DISCORD_BOT_TOKEN, DISCORD_CHANNEL_ID, and your AI provider credentials
```

### Run

```bash
# Fetch and summarize today's links
python discord_digest.py

# Search everything you've saved
python search.py "your question here"
```

---

## Scripts

| Script | Purpose |
|--------|---------|
| `discord_digest.py` | Fetch new links from Discord, summarize, save digest + DB |
| `search.py` | Hybrid semantic + keyword search across all saved articles |
| `retry.py` | Re-summarize entries that failed (e.g. Ollama was offline) |
| `backfill.py` | One-time import of existing digest markdown files into SQLite |

### Retry failed summaries

If Ollama was offline when the digest ran, some entries will show an error. Fix them without re-fetching Discord:

```bash
python retry.py 2026-05-28   # specific date
python retry.py               # today
```

---

## AI / portfolio notes

This project demonstrates several applied AI engineering patterns:

**Multi-model provider abstraction** — A single `providers.py` module routes summarization and RAG answers to Anthropic, OpenAI, or Ollama based on one env var. Adding a new provider is ~15 lines.

**RAG pipeline** — `search.py` implements retrieval-augmented generation end to end: embed the query → vector search ChromaDB → retrieve article summaries → LLM synthesizes an answer with numbered citations.

**Hybrid search** — Semantic search alone misses exact keyword matches ("RAG", "LLM", specific names). Keyword search alone misses conceptual relevance. Both run on every query; results are merged and deduplicated, semantic results ranked first.

**Operational resilience** — `ensure_ollama()` auto-starts the Ollama server if it's not running, pre-warms the model into VRAM before the first article hits it, and surfaces actionable CUDA/GPU error messages with specific fix options.

**Local-first design** — Embeddings run on a 45 MB model via Ollama. Summaries can run on local LLMs. The only required external service is Discord itself.

---

## Project structure

```
MyLinkInbox/
├── discord_digest.py   # main digest script
├── search.py           # RAG search CLI
├── retry.py            # retry failed entries
├── backfill.py         # import historical digests
├── providers.py        # AI provider abstraction
├── db.py               # SQLite persistence layer
├── requirements.txt
├── .env.example
└── digests/            # generated Markdown files (gitignored)
```
