from __future__ import annotations

import threading
import time

import requests

from .base import LLMAdapter, LLMError

API_ROOT = "https://generativelanguage.googleapis.com/v1beta/models"

# The free tier enforces a low requests-per-minute cap. Rather than only
# reacting to 429s after the fact, every call waits for its turn behind a
# simple shared cooldown -- this keeps a several-hundred-page ingest run
# from burning most of its retries on rate limiting it could have avoided.
MIN_INTERVAL_SECONDS = 4.5
MAX_ATTEMPTS = 4


class GeminiAdapter(LLMAdapter):
    name = "gemini"
    _lock = threading.Lock()
    _last_call_ts = 0.0

    def __init__(self, api_key: str, model: str = "gemini-flash-latest"):
        self.api_key = api_key
        self.model = model

    def _wait_for_turn(self):
        with GeminiAdapter._lock:
            now = time.monotonic()
            wait = MIN_INTERVAL_SECONDS - (now - GeminiAdapter._last_call_ts)
            if wait > 0:
                time.sleep(wait)
            GeminiAdapter._last_call_ts = time.monotonic()

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        url = f"{API_ROOT}/{self.model}:generateContent?key={self.api_key}"
        body: dict = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        if json_mode:
            body["generationConfig"]["response_mime_type"] = "application/json"

        last_err: str | None = None
        for attempt in range(MAX_ATTEMPTS):
            self._wait_for_turn()
            try:
                resp = requests.post(url, json=body, timeout=90)
                if resp.status_code == 429:
                    last_err = "429 rate limited"
                    time.sleep(min(8 * (attempt + 1), 20))
                    continue
                if resp.status_code in (500, 502, 503, 504):
                    last_err = f"{resp.status_code} server error"
                    time.sleep(min(4 * (attempt + 1), 12))
                    continue
                resp.raise_for_status()
                data = resp.json()
                candidates = data.get("candidates") or []
                if not candidates:
                    feedback = data.get("promptFeedback", {})
                    last_err = f"no candidates returned: {feedback}"
                    time.sleep(min(2 * (attempt + 1), 8))
                    continue
                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(p.get("text", "") for p in parts if "text" in p)
                if not text:
                    last_err = "empty response text"
                    time.sleep(min(2 * (attempt + 1), 8))
                    continue
                return text
            except requests.RequestException as e:
                last_err = str(e)
                time.sleep(min(3 * (attempt + 1), 10))
        raise LLMError(f"Gemini call failed after {MAX_ATTEMPTS} attempts: {last_err}")
