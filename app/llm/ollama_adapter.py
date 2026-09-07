from __future__ import annotations

import requests

from .base import LLMAdapter, LLMError


class OllamaAdapter(LLMAdapter):
    """Fully offline fallback. Used when no API key is configured at all."""

    name = "ollama"

    def __init__(self, host: str, model: str, embed_model: str):
        self.host = host.rstrip("/")
        self.model = model
        self.embed_model = embed_model

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        url = f"{self.host}/api/generate"
        body = {
            "model": self.model,
            "system": system,
            "prompt": prompt,
            "stream": False,
            "options": {"temperature": 0.1},
        }
        if json_mode:
            body["format"] = "json"
        try:
            resp = requests.post(url, json=body, timeout=300)
            resp.raise_for_status()
            return resp.json().get("response", "")
        except requests.RequestException as e:
            raise LLMError(
                f"Ollama call failed ({e}). Is `ollama serve` running, "
                f"and has `ollama pull {self.model}` been run?"
            ) from e

    def embed(self, text: str) -> list[float] | None:
        try:
            resp = requests.post(
                f"{self.host}/api/embeddings",
                json={"model": self.embed_model, "prompt": text},
                timeout=30,
            )
            resp.raise_for_status()
            vec = resp.json().get("embedding")
            return vec if vec else None
        except requests.RequestException:
            return None
