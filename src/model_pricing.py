"""Provider model pricing catalogs and lookup helpers.

Provider APIs do not consistently return per-model price metadata. Keep the
catalogs outside route modules so model discovery, billing adapters, and the
local usage ledger can share one source of truth.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from src.provider_identity import pricing_provider_from_endpoint


_DIGITALOCEAN_PRICING_URL = "https://docs.digitalocean.com/products/inference/details/pricing/"
_OPENAI_PRICING_URL = "https://platform.openai.com/docs/pricing/"
_ANTHROPIC_PRICING_URL = "https://docs.anthropic.com/en/docs/about-claude/pricing"


def _provider_io_price(
    input_usd: float,
    output_usd: float,
    *,
    source: str,
    source_url: str,
    note: Optional[str] = None,
    cache_write_5m_usd: Optional[float] = None,
    cache_write_1h_usd: Optional[float] = None,
    cache_read_usd: Optional[float] = None,
) -> Dict[str, Any]:
    data: Dict[str, Any] = {
        "currency": "USD",
        "unit": "1M tokens",
        "input_usd_per_unit": input_usd,
        "output_usd_per_unit": output_usd,
        "source": source,
        "source_url": source_url,
    }
    if cache_write_5m_usd is not None:
        data["cache_write_5m_usd_per_unit"] = cache_write_5m_usd
    if cache_write_1h_usd is not None:
        data["cache_write_1h_usd_per_unit"] = cache_write_1h_usd
    if cache_read_usd is not None:
        data["cache_read_usd_per_unit"] = cache_read_usd
    if note:
        data["note"] = note
    return data


def _io_price(input_usd: float, output_usd: float, note: Optional[str] = None) -> Dict[str, Any]:
    return _provider_io_price(
        input_usd,
        output_usd,
        source="DigitalOcean Inference pricing",
        source_url=_DIGITALOCEAN_PRICING_URL,
        note=note,
    )


def _openai_io_price(input_usd: float, output_usd: float, note: Optional[str] = None) -> Dict[str, Any]:
    return _provider_io_price(
        input_usd,
        output_usd,
        source="OpenAI API pricing",
        source_url=_OPENAI_PRICING_URL,
        note=note,
    )


def _anthropic_io_price(input_usd: float, output_usd: float, note: Optional[str] = None) -> Dict[str, Any]:
    return _provider_io_price(
        input_usd,
        output_usd,
        source="Anthropic API pricing",
        source_url=_ANTHROPIC_PRICING_URL,
        note=note,
        cache_write_5m_usd=round(input_usd * 1.25, 6),
        cache_write_1h_usd=round(input_usd * 2, 6),
        cache_read_usd=round(input_usd * 0.1, 6),
    )


def _input_price(input_usd: float, unit: str = "1M input tokens") -> Dict[str, Any]:
    return {
        "currency": "USD",
        "unit": unit,
        "input_usd_per_unit": input_usd,
        "source": "DigitalOcean Inference pricing",
        "source_url": _DIGITALOCEAN_PRICING_URL,
    }


def _unit_price(price_usd: float, unit: str) -> Dict[str, Any]:
    return {
        "currency": "USD",
        "unit": unit,
        "price_usd_per_unit": price_usd,
        "source": "DigitalOcean Inference pricing",
        "source_url": _DIGITALOCEAN_PRICING_URL,
    }


# DigitalOcean's /v1/models endpoint does not expose price metadata. Keep this
# catalog provider-scoped so other cloud providers can be added independently.
_DIGITALOCEAN_MODEL_PRICING: Dict[str, Dict[str, Any]] = {
    # Anthropic commercial models billed through DigitalOcean Inference.
    "anthropic-claude-4.6-sonnet": _io_price(3.00, 15.00, "Prompts over 200K tokens have higher rates."),
    "anthropic-claude-4.5-sonnet": _io_price(3.00, 15.00, "Prompts over 200K tokens have higher rates."),
    "anthropic-claude-sonnet-4": _io_price(3.00, 15.00, "Prompts over 200K tokens have higher rates."),
    "anthropic-claude-haiku-4.5": _io_price(1.00, 5.00),
    "anthropic-claude-opus-4.8": _io_price(5.00, 25.00),
    "anthropic-claude-opus-4.7": _io_price(5.00, 25.00),
    "anthropic-claude-opus-4.6": _io_price(5.00, 25.00, "Prompts over 200K tokens have higher rates."),
    "anthropic-claude-opus-4.5": _io_price(5.00, 25.00),
    "anthropic-claude-4.1-opus": _io_price(15.00, 75.00),
    "anthropic-claude-opus-4": _io_price(15.00, 75.00),

    # DigitalOcean-hosted and third-party models exposed by the DO endpoint.
    "arcee-trinity-large-thinking": _io_price(0.25, 0.90),
    "alibaba-qwen3-32b": _io_price(0.25, 0.55),
    "qwen3-coder-flash": _io_price(0.45, 1.70),
    "qwen3.5-397b-a17b": _io_price(0.55, 3.50),
    "qwen3-tts-voicedesign": _unit_price(20.00, "1M character tokens"),
    "wan2.2-t2v-a14b": _unit_price(0.60, "1M video tokens"),
    "wan2-2-t2v-a14b": _unit_price(0.60, "1M video tokens"),
    "deepseek-r1-distill-llama-70b": _io_price(0.99, 0.99),
    "deepseek-v4-pro": _io_price(1.74, 3.48),
    "deepseek-4-flash": _io_price(0.14, 0.28),
    "deepseek-3.2": _io_price(0.50, 1.60),
    "gemma-4-31B-it": _io_price(0.18, 0.50),
    "minimax-m2.5": _io_price(0.30, 1.20, "30% lower during DigitalOcean off-peak hours."),
    "kimi-k2.5": _io_price(0.50, 2.70, "30% lower during DigitalOcean off-peak hours."),
    "kimi-k2.6": _io_price(0.95, 4.00),
    "llama3.3-70b-instruct": _io_price(0.65, 0.65),
    "llama-4-maverick": _io_price(0.25, 0.87),
    "mistral-3-14B": _io_price(0.20, 0.20),
    "nvidia-nemotron-3-super-120b": _io_price(0.30, 0.65),
    "nemotron-3-nano-omni": _io_price(0.50, 0.90),
    "nemotron-nano-12b-v2-vl": _io_price(0.20, 0.60),
    "stable-diffusion-3.5-large": _unit_price(0.08, "1M image tokens"),
    "glm-5": _io_price(1.00, 3.20),

    # OpenAI commercial models billed through DigitalOcean Inference.
    "openai-gpt-oss-120b": _io_price(0.10, 0.70),
    "openai-gpt-oss-20b": _io_price(0.05, 0.45),
    "openai-gpt-5.4": _io_price(2.50, 15.00),
    "openai-gpt-5.4-mini": _io_price(0.75, 4.50),
    "openai-gpt-5.4-nano": _io_price(0.20, 1.25),
    "openai-gpt-5.4-pro": _io_price(30.00, 180.00),
    "openai-gpt-5.3-codex": _io_price(1.75, 14.00),
    "openai-gpt-5.2": _io_price(1.75, 14.00),
    "openai-gpt-5-2-pro": _io_price(21.00, 168.00),
    "openai-gpt-5.2-pro": _io_price(21.00, 168.00),
    "openai-gpt-5.1-codex-max": _io_price(1.25, 10.00),
    "openai-gpt-5": _io_price(1.25, 10.00),
    "openai-gpt-5-mini": _io_price(0.25, 2.00),
    "openai-gpt-5-nano": _io_price(0.05, 0.40),
    "openai-gpt-4.1": _io_price(2.00, 8.00),
    "openai-gpt-4o": _io_price(2.50, 10.00),
    "openai-gpt-4o-mini": _io_price(0.15, 0.60),
    "openai-o1": _io_price(15.00, 60.00),
    "openai-o3": _io_price(2.00, 8.00),
    "openai-o3-mini": _io_price(1.10, 4.40),
    "openai-gpt-image-1": _io_price(5.00, 40.00),
    "openai-gpt-image-1.5": _io_price(5.00, 10.00),

    # Knowledge-base embeddings and reranking.
    "all-mini-lm-l6-v2": _input_price(0.009),
    "multi-qa-mpnet-base-dot-v1": _input_price(0.009),
    "gte-large-en-v1.5": _input_price(0.09),
    "qwen3-embedding-0.6b": _input_price(0.04),
    "bge-m3": _input_price(0.02),
    "e5-large-v2": _input_price(0.02),
    "bge-reranker-v2-m3": _unit_price(0.01, "1M reranking tokens"),
}


_OPENAI_MODEL_PRICING: Dict[str, Dict[str, Any]] = {
    "gpt-5": _openai_io_price(2.00, 8.00),
    "gpt-4.1": _openai_io_price(2.00, 8.00),
    "gpt-4.1-mini": _openai_io_price(0.40, 1.60),
    "gpt-4.1-nano": _openai_io_price(0.10, 0.40),
    "gpt-4o": _openai_io_price(2.50, 10.00),
    "gpt-4o-mini": _openai_io_price(0.15, 0.60),
    "gpt-4-turbo": _openai_io_price(10.00, 30.00),
    "o1": _openai_io_price(15.00, 60.00),
    "o1-mini": _openai_io_price(3.00, 12.00),
    "o1-pro": _openai_io_price(150.00, 600.00),
    "o3": _openai_io_price(2.00, 8.00),
    "o3-mini": _openai_io_price(1.10, 4.40),
    "o4-mini": _openai_io_price(1.10, 4.40),
}


_ANTHROPIC_MODEL_PRICING: Dict[str, Dict[str, Any]] = {
    "claude-opus-4-8": _anthropic_io_price(5.00, 25.00),
    "claude-opus-4-7": _anthropic_io_price(5.00, 25.00),
    "claude-opus-4-6": _anthropic_io_price(5.00, 25.00),
    "claude-opus-4-5": _anthropic_io_price(5.00, 25.00),
    "claude-opus-4-1": _anthropic_io_price(15.00, 75.00),
    "claude-opus-4": _anthropic_io_price(15.00, 75.00),
    "claude-sonnet-4-6": _anthropic_io_price(3.00, 15.00),
    "claude-sonnet-4-5": _anthropic_io_price(3.00, 15.00),
    "claude-sonnet-4": _anthropic_io_price(3.00, 15.00),
    "claude-haiku-4-5": _anthropic_io_price(1.00, 5.00),
    "claude-haiku-3-5": _anthropic_io_price(0.80, 4.00),
    "claude-3-5-sonnet": _anthropic_io_price(3.00, 15.00),
    "claude-3-5-haiku": _anthropic_io_price(0.80, 4.00),
    "claude-3-opus": _anthropic_io_price(15.00, 75.00),
    "claude-3-sonnet": _anthropic_io_price(3.00, 15.00),
    "claude-3-haiku": _anthropic_io_price(0.25, 1.25),
}


_MODEL_PRICING_BY_PROVIDER: Dict[str, Dict[str, Dict[str, Any]]] = {
    "digitalocean": _DIGITALOCEAN_MODEL_PRICING,
    "openai": _OPENAI_MODEL_PRICING,
    "anthropic": _ANTHROPIC_MODEL_PRICING,
}


def _match_pricing_provider(base_url: str) -> Optional[str]:
    return pricing_provider_from_endpoint(base_url)


def _model_pricing_for_provider(provider: str, model_id: str) -> Optional[Dict[str, Any]]:
    pricing_map = _MODEL_PRICING_BY_PROVIDER.get((provider or "").strip().lower()) or {}
    model_key = str(model_id or "").strip().lower()
    if not pricing_map or not model_key:
        return None

    for key, pricing in pricing_map.items():
        if key.lower() == model_key:
            return dict(pricing)

    matches = [
        (len(key), key, pricing)
        for key, pricing in pricing_map.items()
        if key.lower() in model_key
    ]
    if not matches:
        return None
    _, _, pricing = max(matches, key=lambda item: item[0])
    return dict(pricing)


def _model_pricing_for_endpoint(base_url: str, model_id: str) -> Optional[Dict[str, Any]]:
    provider = _match_pricing_provider(base_url)
    if not provider:
        return None
    pricing = _model_pricing_for_provider(provider, model_id)
    if not pricing:
        return None
    pricing["provider"] = provider
    return pricing


def _model_pricing_map(base_url: str, model_ids: list[str]) -> Dict[str, Dict[str, Any]]:
    pricing: Dict[str, Dict[str, Any]] = {}
    for model_id in model_ids:
        item = _model_pricing_for_endpoint(base_url, model_id)
        if item:
            pricing[model_id] = item
    return pricing
