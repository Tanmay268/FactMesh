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

# Discovered the hard way while building this: Google's free tier gives each
# MODEL NAME its own separate daily request quota, and they vary wildly --
# from 20/day to 500/day -- with no way to know which in advance. A model
# picked at the start of a long ingest run can run out of quota partway
# through. Rather than let that abort the run, the adapter falls back
# through this list (after the configured model, tried first) and keeps
# going on the next one -- sticky for the rest of the process, so it
# doesn't thrash back and forth once a working model is found.
FALLBACK_MODELS = [
    "gemini-flash-lite-latest",
    "gemini-3.1-flash-lite-preview",
    "gemini-3-flash-preview",
    "gemini-flash-latest",
    "gemini-pro-latest",
]


class GeminiAdapter(LLMAdapter):
    name = "gemini"
    _lock = threading.Lock()
    _last_call_ts = 0.0

    def __init__(self, api_key: str, model: str = "gemini-flash-lite-latest"):
        self.api_key = api_key
        # The configured model is tried first; fallbacks follow, de-duplicated.
        self._models = [model] + [m for m in FALLBACK_MODELS if m != model]
        self._model_index = 0

    @property
    def model(self) -> str:
        return self._models[self._model_index]

    def _wait_for_turn(self):
        with GeminiAdapter._lock:
            now = time.monotonic()
            wait = MIN_INTERVAL_SECONDS - (now - GeminiAdapter._last_call_ts)
            if wait > 0:
                time.sleep(wait)
            GeminiAdapter._last_call_ts = time.monotonic()

    def _call_once(self, model: str, body: dict) -> tuple[str | None, str | None, bool]:
        """Returns (text, error, is_daily_quota_exhausted)."""
        url = f"{API_ROOT}/{model}:generateContent?key={self.api_key}"
        try:
            resp = requests.post(url, json=body, timeout=90)
        except requests.RequestException as e:
            return None, str(e), False

        if resp.status_code == 429:
            exhausted = "PerDay" in resp.text or "RESOURCE_EXHAUSTED" in resp.text
            return None, "429 rate limited", exhausted
        if resp.status_code in (500, 502, 503, 504):
            return None, f"{resp.status_code} server error", False
        try:
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, ValueError) as e:
            return None, str(e), False

        candidates = data.get("candidates") or []
        if not candidates:
            return None, f"no candidates returned: {data.get('promptFeedback', {})}", False
        parts = candidates[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts if "text" in p)
        if not text:
            return None, "empty response text", False
        return text, None, False

    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        body: dict = {
            "system_instruction": {"parts": [{"text": system}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.1},
        }
        if json_mode:
            body["generationConfig"]["response_mime_type"] = "application/json"

        last_err: str | None = None
        while True:
            for attempt in range(MAX_ATTEMPTS):
                self._wait_for_turn()
                text, err, daily_exhausted = self._call_once(self.model, body)
                if text is not None:
                    return text
                last_err = err
                if daily_exhausted:
                    break  # no point retrying this model -- fall over instead
                sleep_s = min(4 * (attempt + 1), 15)
                time.sleep(sleep_s)
            else:
                # Exhausted all attempts on this model without a daily-quota
                # signal (transient errors) -- give up rather than fall over,
                # since the problem likely isn't this model specifically.
                raise LLMError(f"Gemini call failed after {MAX_ATTEMPTS} attempts on {self.model}: {last_err}")

            if self._model_index + 1 < len(self._models):
                self._model_index += 1
                continue  # retry the same request on the next model
            raise LLMError(
                f"Gemini call failed: every model tried is quota-exhausted "
                f"(tried {self._models}); last error: {last_err}"
            )
