# My Link Inbox 📬

A community intelligence pipeline that ingests Discord conversations and produces structured, LLM-generated digests — automatically extracting signal from noise across high-volume channels.

---

## Why I Built This

Anyone active in multiple Discord communities knows the problem: valuable information gets buried in hundreds of messages per day. Keeping up manually is a part-time job. Ignoring it means missing important context, links, and discussions that are actually relevant to your work.

My Link Inbox solves this by treating Discord channels as a structured data source — ingesting messages, filtering for signal, and producing clean summaries that take two minutes to read instead of two hours.

This project is also part of a broader AI orchestration system — [AI Ops](https://github.com/ckcreativeandconsulting/ai-ops) — which can schedule and trigger My Link Inbox automatically on a defined cadence.

---

## What It Does

- **Ingests Discord channel messages** on a configurable schedule
- **Filters for high-signal content** — links, announcements, discussions with high engagement
- **Generates structured digests** using LLMs — organized by topic, not just chronologically
- **Delivers summaries** in a clean, readable format
- **Maintains an inbox** of saved links and references for later review

A companion CLI lets you query everything you've saved:

```bash
python search.py "what did I read about AI agents last week?"
python search.py "economy articles" --top-k 20
```

Search combines semantic similarity (ChromaDB vectors) and keyword matching (SQLite `LIKE`) — so you get both conceptual relevance and exact-term recall.

---

## The Pattern This Represents

The underlying architecture — ingest unstructured communications, extract signal, produce structured summaries — is reusable across many business contexts:

- Internal Slack channels drowning in noise
- Customer support ticket summarization
- Community feedback aggregation
- Competitive intelligence monitoring

---

## AI Provider Flexibility

One of the core design goals was being able to run this entirely locally — no API costs, no data leaving your machine:

| Provider | Cost | Privacy | Quality |
|----------|------|---------|---------|
| Local Ollama model | Free | Full — runs on your hardware | Good (depends on model) |
| OpenAI GPT-4 | API costs | Cloud | Excellent |
| Anthropic Claude | API costs | Cloud | Excellent |

Switch providers via a single config setting. For local use, any Ollama-compatible model works.

---

## Tech Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.10+ |
| Persistence | SQLite (summaries + metadata), ChromaDB (vector index) |
| Embeddings | Ollama `all-minilm` — local, 45 MB, runs on CPU |
| AI providers | Anthropic Claude · OpenAI GPT · Ollama local LLMs |
| Web scraping | `requests` + `BeautifulSoup` |
| Discord | REST API v10 via `requests` (no Discord SDK needed) |

---

## Getting Started

### Prerequisites

- Python 3.10+
- Discord Bot token (see [Discord Developer Portal](https://discord.com/developers/applications))
- One of: Ollama installed locally, OpenAI API key, or Anthropic API key

### Setup

```bash
git clone https://github.com/ckcreativeandconsulting/my-link-inbox.git
cd my-link-inbox
pip install -r requirements.txt
cp .env.example .env
# Edit .env with your Discord token and preferred AI provider
```

### Run

```bash
# Fetch and summarize today's links
python discord_digest.py

# Search your archive
python search.py "your query here"
```

### Configuration

```
# Discord
DISCORD_BOT_TOKEN=your_token_here
DISCORD_CHANNEL_ID=your_channel_id

# AI Provider — choose one
AI_PROVIDER=ollama          # local, free
# AI_PROVIDER=openai
# AI_PROVIDER=anthropic

# If using local Ollama
OLLAMA_MODEL=llama3.1:8b

# If using API
OPENAI_API_KEY=your_key_here
ANTHROPIC_API_KEY=your_key_here
```

---

## How It Fits the Bigger Picture

My Link Inbox is one of the agents in my personal AI operations system:

```
AI Ops (Orchestrator)
├── Job Agent        (job search automation)
└── My Link Inbox    ← this repo
```

When run through AI Ops, My Link Inbox is triggered on a schedule, its outputs are logged centrally, and summaries are routed automatically. See the [AI Ops repo](https://github.com/ckcreativeandconsulting/ai-ops) for details.

---

## Key Learnings

- **Prompt design for summarization is harder than it looks** — naive summarization loses the links and references that make digests actually useful
- **Discord's API has rate limits that require careful batching** — this is a microcosm of the real-world data engineering challenges in any pipeline
- **The most useful output format turned out to be topic-clustered rather than chronological** — LLMs are surprisingly good at inferring topic groupings from message context
- **This pattern (ingest → filter → summarize → deliver) is one of the highest-value AI use cases** for any organization with high-volume unstructured communications

---

## About

Built by [Charles Kang](https://charleskang.com) · [LinkedIn](https://www.linkedin.com/in/ck-charleskang) · Part of the CK Creative and Consulting portfolio
