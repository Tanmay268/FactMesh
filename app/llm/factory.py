from __future__ import annotations

from app.config import settings

from .anthropic_adapter import AnthropicAdapter
from .base import LLMAdapter
from .gemini import GeminiAdapter
from .ollama_adapter import OllamaAdapter
from .openai_adapter import OpenAIAdapter

_adapter: LLMAdapter | None = None
_embedder: OllamaAdapter | None = None


def get_adapter() -> LLMAdapter:
    """
    The one text-generation adapter the whole app uses, chosen once from
    whichever key is configured (see Settings.active_provider). Cached so we
    don't re-read env vars on every call.
    """
    global _adapter
    if _adapter is not None:
        return _adapter

    provider = settings.active_provider
    if provider == "gemini":
        _adapter = GeminiAdapter(settings.gemini_api_key)  # type: ignore[arg-type]
    elif provider == "openai":
        _adapter = OpenAIAdapter(settings.openai_api_key)  # type: ignore[arg-type]
    elif provider == "anthropic":
        _adapter = AnthropicAdapter(settings.anthropic_api_key)  # type: ignore[arg-type]
    else:
        _adapter = OllamaAdapter(
            settings.ollama_host, settings.ollama_model, settings.ollama_embed_model
        )
    return _adapter


def get_embedder() -> OllamaAdapter:
    """
    Embeddings always try local Ollama first (free, offline, already pulled),
    regardless of which provider is doing text generation. If Ollama is not
    running, .embed() returns None and callers fall back to string similarity
    -- see app/linking.py.
    """
    global _embedder
    if _embedder is None:
        _embedder = OllamaAdapter(
            settings.ollama_host, settings.ollama_model, settings.ollama_embed_model
        )
    return _embedder
