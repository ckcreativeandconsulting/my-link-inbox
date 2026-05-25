"""AI provider abstraction for discord_digest.

Supported providers (set AI_PROVIDER in .env):
  anthropic  - Claude via Anthropic API (default)
  openai     - GPT via OpenAI API
  ollama     - Local models via Ollama REST API (no pip package — uses HTTP)
"""

import os
import requests


# ---------------------------------------------------------------------------
# Private: one completion function per provider, accepts any prompt string
# ---------------------------------------------------------------------------

def _anthropic_complete(prompt: str) -> str:
    import anthropic  # lazy import — only needed when provider=anthropic
    model = os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-6")
    api_key = os.environ.get("ANTHROPIC_API_KEY", "")
    client = anthropic.Anthropic(api_key=api_key) if api_key else anthropic.Anthropic()
    msg = client.messages.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return msg.content[0].text.strip()


def _openai_complete(prompt: str) -> str:
    import openai  # lazy import — only needed when provider=openai
    model = os.environ.get("OPENAI_MODEL", "gpt-4o")
    api_key = os.environ.get("OPENAI_API_KEY", "")
    client = openai.OpenAI(api_key=api_key)
    resp = client.chat.completions.create(
        model=model,
        max_tokens=512,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.choices[0].message.content.strip()


def _ollama_complete(prompt: str) -> str:
    # Uses Ollama's REST API directly — no pip package required
    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
            },
            timeout=120,
        )
    except requests.exceptions.ConnectionError:
        raise RuntimeError(
            f"Could not connect to Ollama at {base_url}. "
            "Make sure Ollama is running (ollama serve)."
        )
    if not resp.ok:
        # Ollama puts the real reason in the JSON body (e.g. "model not found")
        try:
            detail = resp.json().get("error", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"Ollama /api/chat error ({resp.status_code}): {detail}\n"
            f"Model: {model} — run 'ollama pull {model}' if not downloaded."
        )
    return resp.json()["message"]["content"].strip()


def _route(prompt: str) -> str:
    """Route a prompt to the configured AI provider."""
    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    if provider == "anthropic":
        return _anthropic_complete(prompt)
    elif provider == "openai":
        return _openai_complete(prompt)
    elif provider == "ollama":
        return _ollama_complete(prompt)
    else:
        raise ValueError(
            f"Unknown AI_PROVIDER '{provider}'. "
            "Valid options: anthropic, openai, ollama"
        )


# ---------------------------------------------------------------------------
# Public: summarize a web page
# ---------------------------------------------------------------------------

_SUMMARIZE_PROMPT = (
    "Summarize the following web page content in 3–5 sentences. "
    "Focus on the key points a reader would want to know.\n\n"
    "URL: {url}\n\n---\n{content}\n---"
)


def summarize(url: str, content: str) -> str:
    """Summarize page content using the configured AI provider."""
    return _route(_SUMMARIZE_PROMPT.format(url=url, content=content))


# ---------------------------------------------------------------------------
# Public: answer a question given retrieved RAG context
# ---------------------------------------------------------------------------

_ANSWER_PROMPT = (
    "You are a search assistant for a personal link digest. "
    "Answer the question below using only the provided article summaries. "
    "When mentioning an article, always cite it by its number (e.g. #1, #34) "
    "so the user can find it in the reference list printed above. "
    "Be concise and specific. If the summaries don't contain enough information, say so.\n\n"
    "Question: {question}\n\n"
    "Relevant articles:\n{context}"
)


def answer(question: str, context: str) -> str:
    """Answer a question using retrieved article summaries as context."""
    return _route(_ANSWER_PROMPT.format(question=question, context=context))
