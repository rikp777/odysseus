"""Shared model capability heuristics."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Optional, TypeVar

T = TypeVar("T")

# Prefixes/substrings for provider model IDs that are not safe to send to
# chat-completions endpoints. Keep this backend-only source of truth in sync
# with provider behavior, not with one route's UI needs.
_NON_CHAT_PREFIXES = (
    "dall-e",
    "tts-",
    "whisper",
    "text-embedding",
    "embedding",
    "davinci",
    "babbage",
    "moderation",
    "omni-moderation",
    "sora",
    "gpt-image",
    "chatgpt-image",
    "stable-diffusion",
    "all-mini-lm",
    "multi-qa-",
    "bge-",
    "e5-",
    "gte-",
    "clip",
)

_NON_CHAT_CONTAINS = (
    "-realtime",
    "-transcribe",
    "-tts",
    "embedding",
    "rerank",
    "reranker",
    "/clip",
    "-clip",
    "gpt-image",
    "stable-diffusion",
    "diffusion",
    "t2v",
    "text-to-audio",
    "stable-audio",
)

_NON_CHAT_EXACT_PREFIXES = (
    "gpt-audio",  # gpt-audio, gpt-audio-mini etc.; not gpt-4o-audio-preview.
    "gpt-3.5-turbo-instruct",  # legacy OpenAI completions model.
)

_NON_CHAT_EXACT = {
    # DigitalOcean lists this in /v1/models, but its chat endpoint returns:
    # "This is not a chat model ... Did you mean to use v1/completions?"
    "openai-gpt-5.4-pro",
}


def is_chat_model(model_id: object) -> bool:
    """Return True when a provider model ID looks chat-completions capable."""
    mid = str(model_id or "").strip().lower()
    if not mid or mid in _NON_CHAT_EXACT:
        return False
    if any(mid.startswith(prefix) for prefix in _NON_CHAT_PREFIXES):
        return False
    if any(mid.startswith(prefix) for prefix in _NON_CHAT_EXACT_PREFIXES):
        return False
    if any(substr in mid for substr in _NON_CHAT_CONTAINS):
        return False
    return True


def filter_chat_models(models: Iterable[T] | None) -> list[T]:
    """Return only chat-capable model IDs, preserving order and values."""
    return [model for model in (models or []) if is_chat_model(model)]


def first_chat_model(models: Iterable[T] | None) -> Optional[T]:
    """Return the first chat-capable model, or None if there is no safe choice."""
    for model in models or []:
        if is_chat_model(model):
            return model
    return None


def _model_basename(model_id: object) -> str:
    return str(model_id or "").strip().rstrip("/").rsplit("/", 1)[-1]


def resolve_served_chat_model(configured_model: object, served_models: Iterable[T] | None) -> Optional[T]:
    """Resolve a configured model against served IDs without falling back to non-chat models.

    Prefer an exact chat-capable served ID, then a basename match for endpoints
    that expose IDs with provider/path prefixes, then the first chat-capable
    served model.
    """
    models = list(served_models or [])
    configured = str(configured_model or "").strip()
    if configured:
        for model in models:
            if str(model or "").strip() == configured and is_chat_model(model):
                return model
        configured_base = _model_basename(configured)
        if configured_base:
            for model in models:
                if _model_basename(model) == configured_base and is_chat_model(model):
                    return model
    return first_chat_model(models)
