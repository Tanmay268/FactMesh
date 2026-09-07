from __future__ import annotations

import time

import requests

from .base import LLMAdapter, LLMError


class OpenAIAdapter(LLMAdapter):
    name = "openai"

    def __init__(self, api_key: str, model: str = "gpt-4.1-mini"):
        self.api_key = api_key
        self.model = model

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        url = "https://api.openai.com/v1/chat/completions"
        headers = {"Authorization": f"Bearer {self.api_key}"}
        body: dict = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.1,
        }
        if json_mode:
            body["response_format"] = {"type": "json_object"}

        last_err: Exception | None = None
        for attempt in range(3):
            try:
                resp = requests.post(url, json=body, headers=headers, timeout=90)
                if resp.status_code == 429:
                    time.sleep(3 * (attempt + 1))
                    continue
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"]
            except requests.RequestException as e:
                last_err = e
                time.sleep(2 * (attempt + 1))
        raise LLMError(f"OpenAI call failed after retries: {last_err}")

    def embed(self, text: str) -> list[float] | None:
        try:
            resp = requests.post(
                "https://api.openai.com/v1/embeddings",
                json={"model": "text-embedding-3-small", "input": text},
                headers={"Authorization": f"Bearer {self.api_key}"},
                timeout=30,
            )
            resp.raise_for_status()
            return resp.json()["data"][0]["embedding"]
        except Exception:
            return None
