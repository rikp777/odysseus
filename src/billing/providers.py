"""Billing provider registry and metadata."""

from __future__ import annotations

from typing import Any, Dict

from src.billing.adapters.anthropic import _anthropic_payload, _fetch_anthropic_billing
from src.billing.adapters.digitalocean import _digitalocean_payload, _fetch_digitalocean_balance
from src.billing.adapters.openai import _fetch_openai_billing, _openai_payload
from src.billing.provider_types import BillingProvider


def _digitalocean_provider() -> BillingProvider:
    return BillingProvider(
        id="digitalocean",
        label="DigitalOcean",
        short_label="DO",
        token_hint="DigitalOcean token with billing:read and account:read",
        fetch=_fetch_digitalocean_balance,
        normalize=_digitalocean_payload,
    )


def _openai_provider() -> BillingProvider:
    return BillingProvider(
        id="openai",
        label="OpenAI",
        short_label="OA",
        token_hint="OpenAI admin key with organization usage/costs access",
        fetch=_fetch_openai_billing,
        normalize=_openai_payload,
    )


def _anthropic_provider() -> BillingProvider:
    return BillingProvider(
        id="anthropic",
        label="Anthropic",
        short_label="CL",
        token_hint="Anthropic Admin API key",
        fetch=_fetch_anthropic_billing,
        normalize=_anthropic_payload,
    )


def create_provider_registry() -> Dict[str, BillingProvider]:
    providers = [
        _digitalocean_provider(),
        _openai_provider(),
        _anthropic_provider(),
    ]
    return {provider.id: provider for provider in providers}


_PROVIDERS = create_provider_registry()


def _provider_meta(provider: str) -> Dict[str, str]:
    definition = _PROVIDERS.get(provider)
    label = definition.label if definition else provider or "Cloud provider"
    return {
        "provider": provider,
        "provider_label": label,
        "provider_short_label": definition.short_label if definition else label[:2].upper(),
        "provider_token_hint": definition.token_hint if definition else "Provider billing API token",
    }


def _normalized_provider(value: Any) -> str:
    provider = str(value or "digitalocean").strip().lower()
    return provider or "digitalocean"
