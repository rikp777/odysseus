"""Billing status diagnostics derived from public billing payloads."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict, Optional

from src.billing.common import decimal_or_none, money


def _amount_display(value: Optional[Decimal]) -> str:
    return f"${money(value or Decimal('0'))}"


def _provider_account_total(accounts: list[Dict[str, Any]]) -> Optional[Decimal]:
    total = Decimal("0")
    found = False
    for item in accounts:
        if not item.get("ok"):
            continue
        if str(item.get("amount_scope") or "provider_account") != "provider_account":
            continue
        amount = decimal_or_none(item.get("amount"))
        if amount is None:
            continue
        total += amount
        found = True
    return total if found else None


def _provider_model_total(accounts: list[Dict[str, Any]]) -> Optional[Decimal]:
    total = Decimal("0")
    found = False
    for item in accounts:
        if not item.get("ok"):
            continue
        model_amount = decimal_or_none(item.get("model_amount"))
        if model_amount is None and str(item.get("amount_scope") or "") == "model_usage":
            model_amount = decimal_or_none(item.get("amount"))
        if model_amount is None:
            continue
        total += model_amount
        found = True
    return total if found else None


def _health_label(account: Dict[str, Any], *, can_read_account_total: bool, can_read_model_usage: bool) -> str:
    if not account.get("enabled", True):
        return "Disabled"
    if not account.get("configured"):
        return "Token missing"
    if not account.get("ok"):
        status = str(account.get("status") or "").strip()
        if status == "unsupported_provider":
            return "Unsupported"
        if status == "missing_token":
            return "Token missing"
        return "Failed"
    if can_read_account_total and can_read_model_usage:
        return "Model and account"
    if can_read_model_usage:
        return "Model billing"
    if can_read_account_total:
        return "Account total"
    return "Connected"


def provider_health(payload: Dict[str, Any], *, cache_age_seconds: int = 0) -> list[Dict[str, Any]]:
    """Return token/access health for each billing account without secrets."""

    accounts = [item for item in payload.get("accounts", []) if isinstance(item, dict)]
    health: list[Dict[str, Any]] = []
    for item in accounts:
        amount_scope = str(item.get("amount_scope") or "provider_account")
        model_amount = decimal_or_none(item.get("model_amount"))
        if model_amount is None and amount_scope == "model_usage":
            model_amount = decimal_or_none(item.get("amount"))
        account_amount = decimal_or_none(item.get("amount")) if amount_scope == "provider_account" else None
        can_read_account_total = bool(item.get("ok") and account_amount is not None)
        can_read_model_usage = bool(item.get("ok") and model_amount is not None)
        checked_at = str(item.get("updated_at") or payload.get("updated_at") or "")
        error = str(item.get("error") or "").strip()
        row = {
            "account_id": item.get("account_id") or item.get("id") or "",
            "account_label": item.get("account_label") or item.get("label") or "",
            "provider": item.get("provider") or "",
            "provider_label": item.get("provider_label") or item.get("provider") or "Provider",
            "enabled": bool(item.get("enabled", True)),
            "configured": bool(item.get("configured")),
            "ok": bool(item.get("ok")),
            "status": item.get("status") or "",
            "status_label": _health_label(
                item,
                can_read_account_total=can_read_account_total,
                can_read_model_usage=can_read_model_usage,
            ),
            "can_read_account_total": can_read_account_total,
            "account_total_display": _amount_display(account_amount) if can_read_account_total else "",
            "can_read_model_usage": can_read_model_usage,
            "model_spend_display": _amount_display(model_amount) if can_read_model_usage else "",
            "last_checked_at": checked_at,
            "last_success_at": checked_at if item.get("ok") else "",
            "last_error": error if not item.get("ok") else "",
            "cached": bool(payload.get("cached") or item.get("cached")),
            "cache_age_seconds": int(cache_age_seconds or 0),
            "refresh_seconds": int(item.get("refresh_seconds") or payload.get("refresh_seconds") or 0),
        }
        health.append(row)
    return health


def spend_audit(payload: Dict[str, Any], *, cache_age_seconds: int = 0) -> Dict[str, Any]:
    """Return a compact audit summary for reconciling billing sources."""

    accounts = [item for item in payload.get("accounts", []) if isinstance(item, dict)]
    health = provider_health(payload, cache_age_seconds=cache_age_seconds)
    account_total = _provider_account_total(accounts)
    provider_model_total = _provider_model_total(accounts)
    local_usage = payload.get("local_usage") if isinstance(payload.get("local_usage"), dict) else {}
    local_amount = decimal_or_none(local_usage.get("amount"))
    selected_amount = decimal_or_none(payload.get("amount"))
    selected_is_model_usage = str(payload.get("spend_scope") or "") == "model_usage"

    return {
        "period": payload.get("period") or "month",
        "currency": payload.get("currency") or "USD",
        "selected_source": payload.get("source_label") or payload.get("spend_source") or "",
        "selected_source_kind": payload.get("spend_source") or "",
        "selected_scope": payload.get("spend_scope") or "",
        "model_spend_display": (
            _amount_display(selected_amount) if selected_is_model_usage and selected_amount is not None else ""
        ),
        "model_spend_used_for_limits": bool(selected_is_model_usage and selected_amount is not None),
        "provider_model_billing": {
            "available": provider_model_total is not None,
            "display": _amount_display(provider_model_total) if provider_model_total is not None else "",
            "accounts": sum(1 for item in health if item.get("can_read_model_usage")),
        },
        "provider_account_total": {
            "available": account_total is not None,
            "display": _amount_display(account_total) if account_total is not None else "",
            "accounts": sum(1 for item in health if item.get("can_read_account_total")),
            "scope": "all provider services",
        },
        "local_usage": {
            "enabled": local_usage.get("enabled") is not False,
            "available": local_amount is not None,
            "display": local_usage.get("display") or (_amount_display(local_amount) if local_amount is not None else ""),
            "events": int(local_usage.get("events") or 0),
            "known_cost_events": int(local_usage.get("known_cost_events") or 0),
            "unknown_cost_events": int(local_usage.get("unknown_cost_events") or 0),
        },
        "provider_health": {
            "accounts": len(health),
            "configured": sum(1 for item in health if item.get("configured")),
            "connected": sum(1 for item in health if item.get("ok")),
            "errors": sum(1 for item in health if item.get("configured") and not item.get("ok")),
        },
        "last_refreshed_at": payload.get("updated_at") or "",
        "cached": bool(payload.get("cached")),
        "cache_age_seconds": int(cache_age_seconds or 0),
    }


def attach_billing_diagnostics(payload: Dict[str, Any], *, cache_age_seconds: int = 0) -> Dict[str, Any]:
    payload["provider_health"] = provider_health(payload, cache_age_seconds=cache_age_seconds)
    payload["spend_audit"] = spend_audit(payload, cache_age_seconds=cache_age_seconds)
    return payload
