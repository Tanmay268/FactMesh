"""
The one interface every provider must implement.

Keeping this interface tiny (one method) is deliberate: all the prompt
engineering, JSON parsing and retry logic lives in `extraction.py` and
`reconcile.py`, not duplicated per-provider. Each adapter's only job is
"send this text to the model, optionally ask for JSON, return the text back".
"""
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMError(RuntimeError):
    """Raised when a provider call fails after its retries."""


class LLMAdapter(ABC):
    name: str = "base"

    @abstractmethod
    def generate(self, system: str, prompt: str, json_mode: bool = False) -> str:
        """Return the model's raw text reply. Raise LLMError on failure."""

    def embed(self, text: str) -> list[float] | None:
        """
        Return an embedding vector, or None if this provider does not support
        (or fails at) embeddings. Callers must treat None as "fall back to a
        non-embedding similarity measure" -- it is not an error.
        """
        return None
