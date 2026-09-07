from __future__ import annotations

import time

import requests

from .base import LLMAdapter, LLMError


class AnthropicAdapter(LLMAdapter):
    name = "anthropic"

    def __init__(self, api_key: str, model: str = "claude-haiku-4-5"):
        self.api_key = api_key
        self.model = model

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        # Anthropic has no strict JSON mode; we ask firmly in the prompt and
        # the caller (extraction.py / reconcile.py) parses leniently either way.
        url = "https://api.anthropic.com/v1/messages"
        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
        }
        body = {
            "model": self.model,
            "max_tokens": 4096,
            "system": system,
            "messages": [{"role": "user", "content": prompt}],
            "temperature": 0.1,
        }

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=body, headers=headers, timeout=90)
                if resp.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return "".join(b.get("text", "") for b in data.get("content", []))
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"Anthropic call failed after retries: {last_err}")
