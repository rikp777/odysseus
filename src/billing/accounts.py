"""Billing account settings normalization."""

from __future__ import annotations

import hashlib
from typing import Any, Dict

from src.billing.providers import normalized_provider, provider_meta


def account_id(account: Dict[str, Any], idx: int) -> str:
    raw = str(account.get("id") or "").strip()
    if raw:
        return raw[:80]
    provider = normalized_provider(account.get("provider"))
    label = str(account.get("label") or "").strip()
    digest = hashlib.sha1(f"{provider}:{label}:{idx}".encode("utf-8")).hexdigest()[:10]
    return f"{provider}-{digest}"


def account_label(provider: str, account: Dict[str, Any]) -> str:
    label = str(account.get("label") or "").strip()
    return label or provider_meta(provider)["provider_label"]


def billing_accounts(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw_accounts = settings.get("cloud_billing_accounts")
    if isinstance(raw_accounts, list):
        accounts = []
        for idx, item in enumerate(raw_accounts):
            if not isinstance(item, dict):
                continue
            provider = normalized_provider(item.get("provider"))
            accounts.append({
                "id": account_id(item, idx),
                "provider": provider,
                "label": account_label(provider, item),
                "enabled": bool(item.get("enabled", True)),
                "api_token": str(item.get("api_token") or "").strip(),
            })
        return accounts

    legacy_token = str(settings.get("cloud_billing_api_token") or "").strip()
    legacy_provider = normalized_provider(settings.get("cloud_billing_provider"))
    if legacy_token:
        return [{
            "id": legacy_provider,
            "provider": legacy_provider,
            "label": provider_meta(legacy_provider)["provider_label"],
            "enabled": True,
            "api_token": legacy_token,
        }]
    return []
