"""AI provider abstraction for discord_digest.

Supported providers (set AI_PROVIDER in .env):
  anthropic  - Claude via Anthropic API (default)
  openai     - GPT via OpenAI API
  ollama     - Local models via Ollama REST API (no pip package — uses HTTP)
"""

import os
import subprocess
import time
import requests


# ---------------------------------------------------------------------------
# Public: ensure Ollama is running and the model is loaded (ollama provider only)
# ---------------------------------------------------------------------------

def ensure_ollama() -> None:
    """Ensure Ollama is running and the configured model is loaded.

    1. Health-checks Ollama via GET /api/tags.
    2. If not reachable, starts 'ollama serve' as a detached background process
       and waits up to 30 s for it to become available.
    3. Sends a trivial 'Hi' prompt to force the model to load into VRAM before
       real summarization begins — avoids read-timeout on the first real request.

    No-op when AI_PROVIDER != ollama.
    """
    provider = os.environ.get("AI_PROVIDER", "anthropic").lower()
    if provider != "ollama":
        return

    base_url = os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434")
    model = os.environ.get("OLLAMA_MODEL", "qwen2.5:14b")

    # --- Step 1: health check ---
    def _is_up() -> bool:
        try:
            r = requests.get(f"{base_url}/api/tags", timeout=3)
            return r.ok
        except Exception:
            return False

    if not _is_up():
        print("  Ollama not running — starting 'ollama serve'...")
        kwargs: dict = {"stdout": subprocess.DEVNULL, "stderr": subprocess.DEVNULL}
        if hasattr(subprocess, "CREATE_NEW_PROCESS_GROUP"):
            # Windows: detach so the process outlives this script
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(["ollama", "serve"], **kwargs)

        for i in range(30):
            time.sleep(1)
            if _is_up():
                print(f"  Ollama ready ({i + 1}s).")
                break
        else:
            raise RuntimeError(
                "Ollama did not start within 30 seconds. "
                "Try running 'ollama serve' manually in a terminal."
            )

    # --- Step 2: pre-warm the model ---
    print(f"  Pre-warming model '{model}'...")
    try:
        resp = requests.post(
            f"{base_url}/api/chat",
            json={
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "stream": False,
            },
            timeout=300,  # generous: cold load of a 14b model can take 2–3 min
        )
    except requests.exceptions.Timeout:
        raise RuntimeError(
            f"Model '{model}' took longer than 5 minutes to load. "
            "Try a smaller model (e.g. OLLAMA_MODEL=qwen2.5:7b) or check GPU memory."
        )
    if not resp.ok:
        try:
            detail = resp.json().get("error", resp.text)
        except Exception:
            detail = resp.text
        raise RuntimeError(
            f"Model pre-warm failed ({resp.status_code}): {detail}\n"
            f"Run 'ollama pull {model}' if the model is not downloaded."
        )
    print("  Model ready.")


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
