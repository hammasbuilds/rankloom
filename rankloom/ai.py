"""The AI engine behind Answer Check and Draft Writer: a local Ollama model or any
OpenAI-compatible API (OpenAI, Perplexity, OpenRouter, Groq ...), chosen by environment.

    RANKLOOM_AI=ollama   RANKLOOM_AI_MODEL=qwen2.5:14b-instruct  [RANKLOOM_AI_URL=http://127.0.0.1:11434]
    RANKLOOM_AI=openai   RANKLOOM_AI_MODEL=sonar  RANKLOOM_AI_URL=https://api.perplexity.ai
                         RANKLOOM_AI_KEY=...

Nothing in the product names the model: pages say "the AI engine". With no engine configured,
the sub-tools that need one refuse with the settings to set, rather than inventing output.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from dataclasses import dataclass


class AIUnavailable(Exception):
    """No engine is configured, or the configured one did not answer."""


@dataclass
class Engine:
    kind: str
    model: str
    url: str
    key: str = ""

    def complete(
        self, prompt: str, system: str = "", max_tokens: int = 900, temperature: float = 0.3
    ) -> str:
        messages = ([{"role": "system", "content": system}] if system else []) + [
            {"role": "user", "content": prompt}
        ]
        if self.kind == "ollama":
            body = {
                "model": self.model,
                "messages": messages,
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            data = post(self.url.rstrip("/") + "/api/chat", body, {})
            text = (data.get("message") or {}).get("content", "")
        else:
            body = {
                "model": self.model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            }
            headers = {"Authorization": f"Bearer {self.key}"} if self.key else {}
            data = post(self.url.rstrip("/") + "/chat/completions", body, headers)
            choices = data.get("choices") or [{}]
            text = (choices[0].get("message") or {}).get("content", "")
        text = strip_thinking(text)
        if not text.strip():
            raise AIUnavailable("The AI engine returned an empty answer.")
        return text.strip()


def strip_thinking(text: str) -> str:
    """Reasoning models wrap their scratch work in <think>; only the answer is the answer."""
    while "<think>" in text and "</think>" in text:
        start, end = text.index("<think>"), text.index("</think>") + len("</think>")
        text = text[:start] + text[end:]
    return text


def post(url: str, body: dict, headers: dict) -> dict:
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": "rankloom", **headers},
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            return json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        detail = exc.read()[:300].decode(errors="replace")
        raise AIUnavailable(f"The AI engine answered {exc.code}: {detail}") from exc
    except (urllib.error.URLError, TimeoutError, OSError, ValueError) as exc:
        raise AIUnavailable(f"The AI engine could not be reached: {exc}") from exc


SETUP_HINT = (
    "No AI engine is set up on this server. Set RANKLOOM_AI=ollama with RANKLOOM_AI_MODEL, "
    "or RANKLOOM_AI=openai with RANKLOOM_AI_URL, RANKLOOM_AI_KEY and RANKLOOM_AI_MODEL "
    "(any OpenAI-compatible service, e.g. Perplexity for web-grounded answers)."
)


def engine() -> Engine | None:
    kind = os.environ.get("RANKLOOM_AI", "").strip().lower()
    model = os.environ.get("RANKLOOM_AI_MODEL", "").strip()
    if kind == "ollama" and model:
        return Engine("ollama", model, os.environ.get("RANKLOOM_AI_URL", "http://127.0.0.1:11434"))
    if kind == "openai" and model and os.environ.get("RANKLOOM_AI_URL"):
        return Engine(
            "openai", model, os.environ["RANKLOOM_AI_URL"], os.environ.get("RANKLOOM_AI_KEY", "")
        )
    return None


def require() -> Engine:
    e = engine()
    if e is None:
        raise AIUnavailable(SETUP_HINT)
    return e
