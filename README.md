# My Link Inbox 📬

A personal reading intelligence system — summarize articles before you commit to reading them, build a searchable knowledge base of everything you've saved, and query your entire reading history in natural language.

---

## Why I Built This

I read a lot. Substack newsletters, X threads, news sites, long-form articles — there's more interesting content published every day than any person can meaningfully consume. The problem isn't finding content, it's triage: deciding what's actually worth reading before investing 10-20 minutes in it.

I wanted a system that would:

- **Summarize articles before I read them** — so I could decide in 30 seconds whether something deserved my full attention
- **Build a searchable archive** of everything I'd saved — so "I know I read something about X last month" actually returns an answer
- **Work with local AI** — so I could run it free and keep my reading history completely private
- **Require zero manual effort** — no tagging, no categorizing, no friction

For the delivery mechanism I wanted something free and low-friction. Discord fit perfectly — I already use it, I can drop links from any device in seconds, and the bot can read from a dedicated channel automatically. Discord is the input pipe, not the point.

The result is a daily driver: drop links throughout the day, run the pipeline each morning, and have a summarized digest plus a searchable knowledge base of everything I've ever saved.

This project is also part of a broader AI orchestration system — [AI Ops](https://github.com/ckcreativeandconsulting/ai-ops) — which can schedule and trigger My Link Inbox automatically on a defined cadence.

---

## What It Does

- **Fetches** links you've dropped into a dedicated Discord channel
- **Scrapes** each page for its full text content
- **Summarizes** in 3–5 sentences using the AI provider of your choice — Claude, GPT-4, or a local Ollama model (fully offline, no API costs)
- **Saves** a dated Markdown digest and persists everything to SQLite
- **Indexes** summaries into ChromaDB so your entire reading history is semantically searchable

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
# Clone the repo
git clone https://github.com/ckcreativeandconsulting/my-link-inbox.git
cd my-link-inbox

# Install dependencies
pip install -r requirements.txt

# Configure environment variables
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
- **This pattern (ingest → filter → summarize → deliver) is one of the highest-value AI use cases** for any organization with high-volume unstructured communications
- **Local AI is genuinely viable for this use case** — summarization doesn't require frontier model quality. A well-configured local Ollama model produces summaries good enough to make read/skip decisions, with zero API cost and full privacy.
- **Semantic search changes how you relate to your reading history** — keyword search forces you to remember exact terms. Semantic search lets you query by concept, which is how memory actually works.
- **Discord as infrastructure is underrated** — using it as an input pipe means the system works from any device, requires no custom app, and has zero ongoing maintenance. Sometimes the right architecture decision is the boring one.
- **Discord's API has rate limits that require careful batching** — this is a microcosm of the real-world data engineering challenges in any pipeline
- **The most useful output format turned out to be topic-clustered rather than chronological** — LLMs are surprisingly good at inferring topic groupings from message context

---

## About

Built by [Charles Kang](https://charleskang.com) · [LinkedIn](https://www.linkedin.com/in/ck-charleskang) · Part of the CK Creative and Consulting portfolio
