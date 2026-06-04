"""Endpoint/provider identity helpers shared by model and billing code."""

from __future__ import annotations

import ipaddress
from typing import Optional
from urllib.parse import urlparse


_LOCAL_HOSTS = {"localhost", "127.0.0.1", "0.0.0.0", "::1"}
_TAILSCALE_CGNAT = ipaddress.ip_network("100.64.0.0/10")

_PROVIDER_HOSTS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("digitalocean", ("inference.do-ai.run",)),
    ("openai", ("api.openai.com",)),
    ("anthropic", ("api.anthropic.com", "anthropic.com")),
    ("openrouter", ("openrouter.ai",)),
    ("groq", ("api.groq.com",)),
    ("mistral", ("api.mistral.ai",)),
    ("together", ("api.together.xyz", "api.together.ai")),
    ("fireworks", ("fireworks.ai",)),
    ("google", ("generativelanguage.googleapis.com",)),
    ("xai", ("api.x.ai",)),
)

_PRICING_PROVIDERS = {"digitalocean", "openai", "anthropic"}


def normalize_provider_id(value: object, *, default: str = "") -> str:
    provider = str(value or default).strip().lower()
    return provider or default


def endpoint_host(endpoint_url: str) -> str:
    raw = str(endpoint_url or "").strip()
    try:
        parsed = urlparse(raw)
        host = parsed.hostname or ""
        if not host and raw and "://" not in raw:
            host = urlparse(f"https://{raw}").hostname or ""
        return host.lower().rstrip(".")
    except Exception:
        return ""


def _matches_host(host: str, patterns: tuple[str, ...]) -> bool:
    return any(host == pattern or host.endswith(f".{pattern}") for pattern in patterns)


def provider_from_endpoint(endpoint_url: str) -> str:
    host = endpoint_host(endpoint_url)
    for provider, patterns in _PROVIDER_HOSTS:
        if _matches_host(host, patterns):
            return provider
    return host or "unknown"


def pricing_provider_from_endpoint(endpoint_url: str) -> Optional[str]:
    provider = provider_from_endpoint(endpoint_url)
    if provider in _PRICING_PROVIDERS:
        return provider
    return None


def is_remote_billable_endpoint(endpoint_url: str) -> bool:
    host = endpoint_host(endpoint_url)
    if not host:
        return False
    if host in _LOCAL_HOSTS or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (ip.is_loopback or ip.is_private or ip.is_link_local or ip in _TAILSCALE_CGNAT)
