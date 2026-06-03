"""Tests for provider model pricing catalogs and lookup helpers."""

import pytest

from src.model_pricing import (
    _match_pricing_provider,
    _model_pricing_for_endpoint,
    _model_pricing_for_provider,
    _model_pricing_map,
)


@pytest.mark.parametrize(
    ("base_url", "provider"),
    [
        ("https://inference.do-ai.run/v1", "digitalocean"),
        ("https://api.openai.com/v1", "openai"),
        ("https://api.anthropic.com", "anthropic"),
    ],
)
def test_matches_known_pricing_provider_endpoint(base_url, provider):
    assert _match_pricing_provider(base_url) == provider


def test_unknown_endpoint_has_no_pricing_provider():
    assert _match_pricing_provider("https://api.unknown.example/v1") is None


def test_digitalocean_qwen_price_metadata():
    pricing = _model_pricing_for_endpoint("https://inference.do-ai.run/v1", "qwen3-coder-flash")
    assert pricing is not None
    assert pricing["provider"] == "digitalocean"
    assert pricing["currency"] == "USD"
    assert pricing["unit"] == "1M tokens"
    assert pricing["input_usd_per_unit"] == 0.45
    assert pricing["output_usd_per_unit"] == 1.70


def test_unknown_model_is_omitted_from_pricing_map():
    pricing = _model_pricing_map("https://inference.do-ai.run/v1", ["qwen3-coder-flash", "router:general"])
    assert set(pricing) == {"qwen3-coder-flash"}


def test_openai_pricing_prefers_more_specific_model_key():
    pricing = _model_pricing_for_endpoint("https://api.openai.com/v1", "gpt-4o-mini-2024-07-18")
    assert pricing is not None
    assert pricing["provider"] == "openai"
    assert pricing["input_usd_per_unit"] == 0.15
    assert pricing["output_usd_per_unit"] == 0.60


def test_anthropic_pricing_includes_prompt_cache_rates():
    pricing = _model_pricing_for_provider("anthropic", "claude-sonnet-4-5-20250929")
    assert pricing is not None
    assert pricing["input_usd_per_unit"] == 3.00
    assert pricing["output_usd_per_unit"] == 15.00
    assert pricing["cache_write_5m_usd_per_unit"] == 3.75
    assert pricing["cache_write_1h_usd_per_unit"] == 6.00
    assert pricing["cache_read_usd_per_unit"] == 0.30
