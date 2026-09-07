"""
All environment-driven settings live here, in one place.

Nothing in the rest of the app reads os.environ directly -- it asks this module
instead. That makes it obvious what the app depends on, and makes it easy to
run with no keys at all (everything here has a safe default).
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")


@dataclass(frozen=True)
class Settings:
    gemini_api_key: str | None
    gemini_model: str
    openai_api_key: str | None
    anthropic_api_key: str | None
    ollama_host: str
    ollama_model: str
    ollama_embed_model: str
    database_path: Path
    upload_dir: Path

    @property
    def active_provider(self) -> str:
        """Which LLM provider will actually be used, decided once, up front."""
        if self.gemini_api_key:
            return "gemini"
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "ollama"


def _get(name: str, default: str = "") -> str:
    val = os.environ.get(name, default)
    return val.strip() if val else val


def load_settings() -> Settings:
    db_path = Path(_get("DATABASE_PATH", "data/knowledge.db"))
    if not db_path.is_absolute():
        db_path = ROOT_DIR / db_path
    upload_dir = ROOT_DIR / "data" / "uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)

    return Settings(
        gemini_api_key=_get("GEMINI_API_KEY") or None,
        gemini_model=_get("GEMINI_MODEL", "gemini-flash-lite-latest"),
        openai_api_key=_get("OPENAI_API_KEY") or None,
        anthropic_api_key=_get("ANTHROPIC_API_KEY") or None,
        ollama_host=_get("OLLAMA_HOST", "http://localhost:11434"),
        ollama_model=_get("OLLAMA_MODEL", "qwen3:8b"),
        ollama_embed_model=_get("OLLAMA_EMBED_MODEL", "nomic-embed-text"),
        database_path=db_path,
        upload_dir=upload_dir,
    )


settings = load_settings()
