import httpx

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def polish(transcript: str, model: str | None, api_key: str, prompt: str, timeout: float = 15.0, url: str = OPENROUTER_URL) -> str:
    """Send transcript through an OpenRouter LLM for cleanup.

    Passing model=None (or empty string) bypasses polishing and returns the
    raw transcript — useful for short phrases where LLM latency isn't worth it.
    """
    if not model:
        return transcript
    if not api_key:
        raise RuntimeError("OpenRouter API key not configured")
    if not transcript.strip():
        return transcript

    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": prompt},
            {"role": "user", "content": transcript},
        ],
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://github.com/nickvalenti/murmur",
        "X-Title": "murmur",
    }
    with httpx.Client(timeout=timeout) as client:
        resp = client.post(url, json=body, headers=headers)
        if not resp.is_success:
            raise RuntimeError(f"OpenRouter {resp.status_code}: {resp.text}")
        data = resp.json()
    return data["choices"][0]["message"]["content"].strip()
