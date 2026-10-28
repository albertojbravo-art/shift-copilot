"""Chat-completions client for the conversation layer.

Default transport: POST to Baseten's OpenAI-compatible endpoint for Muse
Spark Open, with the API key read from the BASETEN_API_KEY environment
variable. The key is never stored in this repository and never logged.
A different transport can be injected (tests use a scripted one; local
verification uses the vault's surrogate-credential transport).

The model always reasons before answering, so the token budget is set
generously: a small cap is consumed by reasoning and returns empty
content (verified 2026-10-27 during the API gate).
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

MODEL = "meta-models/muse-spark-open-1026"
URL = "https://inference.baseten.co/v1/chat/completions"
DEFAULT_MAX_TOKENS = 1024


class LLMError(RuntimeError):
    pass


def _default_transport(payload: dict) -> dict:
    key = os.environ.get("BASETEN_API_KEY")
    if not key:
        raise LLMError("BASETEN_API_KEY is not set")
    req = urllib.request.Request(
        URL, data=json.dumps(payload).encode("utf-8"), method="POST"
    )
    req.add_header("Content-Type", "application/json")
    req.add_header("Authorization", f"Bearer {key}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as e:
        raise LLMError(f"model call failed: {e}") from e


def chat_completion(messages, tools=None, transport=None, max_tokens=DEFAULT_MAX_TOKENS) -> dict:
    """One chat-completions round. Returns the response message dict."""
    payload = {"model": MODEL, "messages": messages, "max_tokens": max_tokens}
    if tools:
        payload["tools"] = tools
    data = (transport or _default_transport)(payload)
    try:
        return data["choices"][0]["message"]
    except (KeyError, IndexError, TypeError) as e:
        raise LLMError(f"unexpected model response shape: {e}") from e
