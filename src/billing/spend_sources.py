"""Select the model-spend source exposed in billing status payloads."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from src.billing.common import decimal_or_none, money
from src.billing.providers import normalized_provider, provider_meta


def local_usage_amount(local_usage: Any, *, forced_provider: Optional[str] = None) -> Optional[Decimal]:
    if not isinstance(local_usage, dict) or local_usage.get("enabled") is False:
        return None
    if forced_provider:
        wanted = normalized_provider(forced_provider)
        for item in local_usage.get("providers", []):
            if not isinstance(item, dict):
                continue
            keys = {
                str(item.get("id") or "").strip().lower(),
                str(item.get("label") or "").strip().lower(),
            }
            if wanted in keys:
                return decimal_or_none(item.get("amount")) or Decimal("0")
        return Decimal("0")
    return decimal_or_none(local_usage.get("amount")) or Decimal("0")


def local_usage_provider_meta(
    local_usage: Any,
    *,
    forced_provider: Optional[str] = None,
) -> Dict[str, str]:
    if forced_provider:
        provider = normalized_provider(forced_provider)
        meta = provider_meta(provider)
        return {
            "provider": provider,
            "provider_label": f"{meta['provider_label']} models",
            "provider_short_label": meta["provider_short_label"],
            "provider_token_hint": "Local model usage ledger",
        }

    providers = []
    if isinstance(local_usage, dict):
        for item in local_usage.get("providers", []):
            if not isinstance(item, dict):
                continue
            provider = str(item.get("id") or item.get("label") or "").strip().lower()
            if provider:
                providers.append(provider)

    unique = sorted(set(providers))
    if len(unique) == 1:
        meta = provider_meta(unique[0])
        return {
            "provider": unique[0],
            "provider_label": f"{meta['provider_label']} models",
            "provider_short_label": meta["provider_short_label"],
            "provider_token_hint": "Local model usage ledger",
        }

    return {
        "provider": "local_usage",
        "provider_label": "Model usage",
        "provider_short_label": "AI",
        "provider_token_hint": "Local model usage ledger",
    }


def provider_model_spend_amount(
    payload: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
) -> Optional[Decimal]:
    total = Decimal("0")
    found = False
    wanted = normalized_provider(forced_provider) if forced_provider else ""
    for item in payload.get("accounts", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if wanted and provider != wanted:
            continue
        amount = decimal_or_none(item.get("model_amount"))
        if amount is None:
            continue
        total += amount
        found = True
    return total if found else None


def provider_model_spend_meta(
    payload: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
) -> Dict[str, str]:
    wanted = normalized_provider(forced_provider) if forced_provider else ""
    providers = []
    labels = []
    for item in payload.get("accounts", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if wanted and provider != wanted:
            continue
        if item.get("model_amount") is None:
            continue
        if provider:
            providers.append(provider)
        label = str(item.get("provider_label") or provider or "").strip()
        if label:
            labels.append(label)

    unique = sorted(set(providers))
    if len(unique) == 1:
        meta = provider_meta(unique[0])
        return {
            "provider": unique[0],
            "provider_label": f"{meta['provider_label']} models",
            "provider_short_label": meta["provider_short_label"],
            "provider_token_hint": meta["provider_token_hint"],
        }

    label = labels[0] if len(set(labels)) == 1 and labels else "Model billing"
    return {
        "provider": "provider_model_billing",
        "provider_label": f"{label} models" if label != "Model billing" else label,
        "provider_short_label": "AI",
        "provider_token_hint": "Provider billing API token",
    }


def apply_primary_spend_source(
    payload: Dict[str, Any],
    *,
    settings: Dict[str, Any],
    warning: Optional[Decimal],
    limit: Optional[Decimal],
    forced_provider: Optional[str] = None,
) -> Dict[str, Any]:
    provider_amount = decimal_or_none(payload.get("amount"))
    if (
        provider_amount is not None
        and payload.get("provider") != "local_usage"
        and payload.get("amount_scope", "provider_account") == "provider_account"
    ):
        payload.update({
            "provider_amount": money(provider_amount),
            "provider_display": f"${money(provider_amount)}",
            "provider_spend_scope": "account",
            "provider_source_label": "Provider billing",
        })

    provider_model_amount = provider_model_spend_amount(payload, forced_provider=forced_provider)
    if provider_model_amount is not None:
        payload.update({
            "ok": True,
            "configured": True,
            "status": "ok",
            "error": "",
            "amount": money(provider_model_amount),
            "display": f"${money(provider_model_amount)}",
            "over_warning": bool(warning is not None and provider_model_amount >= warning),
            "over_limit": bool(limit is not None and provider_model_amount >= limit),
            "limit_check_blocked": False,
            "spend_source": "provider_model_billing",
            "spend_scope": "model_usage",
            "source_label": "Provider model billing",
            **provider_model_spend_meta(payload, forced_provider=forced_provider),
        })
        return payload

    if settings.get("cloud_billing_usage_ledger_enabled") is False:
        payload.setdefault("spend_source", "provider_billing")
        payload.setdefault("spend_scope", "provider_account")
        payload.setdefault("source_label", "Provider billing")
        return payload

    amount = local_usage_amount(payload.get("local_usage"), forced_provider=forced_provider)
    if amount is None:
        payload.setdefault("spend_source", "provider_billing")
        payload.setdefault("spend_scope", "provider_account")
        payload.setdefault("source_label", "Provider billing")
        return payload

    provider_status = payload.get("status") or ""
    provider_error = payload.get("error") or ""
    payload.update({
        "ok": True,
        "configured": True,
        "status": "ok",
        "error": "",
        "amount": money(amount),
        "display": f"${money(amount)}",
        "over_warning": bool(warning is not None and amount >= warning),
        "over_limit": bool(limit is not None and amount >= limit),
        "limit_check_blocked": False,
        "spend_source": "usage_ledger",
        "spend_scope": "model_usage",
        "source_label": "Usage ledger",
        **local_usage_provider_meta(payload.get("local_usage"), forced_provider=forced_provider),
    })
    if provider_status and provider_status != "ok":
        payload["provider_status"] = provider_status
    if provider_error:
        payload["provider_error"] = provider_error
    return payload
