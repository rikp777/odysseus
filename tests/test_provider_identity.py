from src.provider_identity import (
    is_remote_billable_endpoint,
    pricing_provider_from_endpoint,
    provider_from_endpoint,
)


def test_provider_from_endpoint_maps_known_hosts():
    assert provider_from_endpoint("https://inference.do-ai.run/v1") == "digitalocean"
    assert provider_from_endpoint("inference.do-ai.run/v1") == "digitalocean"
    assert provider_from_endpoint("https://api.openai.com/v1/chat/completions") == "openai"
    assert provider_from_endpoint("https://api.anthropic.com/v1/messages") == "anthropic"
    assert provider_from_endpoint("https://openrouter.ai/api/v1") == "openrouter"


def test_provider_from_endpoint_uses_host_fallback():
    assert provider_from_endpoint("https://api.unknown.example/v1") == "api.unknown.example"
    assert provider_from_endpoint("https://api.openai.com.evil.test/v1") == "api.openai.com.evil.test"
    assert provider_from_endpoint("") == "unknown"


def test_pricing_provider_only_returns_supported_catalogs():
    assert pricing_provider_from_endpoint("https://inference.do-ai.run/v1") == "digitalocean"
    assert pricing_provider_from_endpoint("https://api.openai.com/v1") == "openai"
    assert pricing_provider_from_endpoint("https://api.anthropic.com/v1") == "anthropic"
    assert pricing_provider_from_endpoint("https://openrouter.ai/api/v1") is None


def test_remote_billable_endpoint_excludes_local_and_private_networks():
    assert is_remote_billable_endpoint("http://localhost:11434/v1") is False
    assert is_remote_billable_endpoint("http://127.0.0.1:11434/v1") is False
    assert is_remote_billable_endpoint("http://192.168.1.10:11434/v1") is False
    assert is_remote_billable_endpoint("http://10.110.0.3:8080/v1") is False
    assert is_remote_billable_endpoint("http://100.64.0.10:8080/v1") is False
    assert is_remote_billable_endpoint("http://model.local:8080/v1") is False
    assert is_remote_billable_endpoint("https://api.openai.com/v1") is True
