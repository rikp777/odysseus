"""Billing account fetch and payload service helpers."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Callable, Dict, Optional

import httpx

from src.billing.common import money as _money
from src.billing.common import utc_now_iso as _utc_now_iso
from src.billing.provider_types import BillingProvider
from src.billing.providers import provider_meta


SecretDecryptor = Callable[[str], str]


def error_payload(
    *,
    provider: str,
    enabled: bool,
    configured: bool,
    warning_usd: Optional[str],
    refresh_seconds: int,
    status: str,
    error: str,
    provider_definition: Optional[BillingProvider] = None,
) -> Dict[str, Any]:
    return {
        "ok": False,
        "enabled": enabled,
        "configured": configured,
        "status": status,
        "error": error,
        "currency": "USD",
        "amount": None,
        "display": "",
        "warning_usd": warning_usd,
        "over_warning": False,
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        **provider_meta(provider, provider_definition),
    }


def account_error_payload(
    *,
    account: Dict[str, Any],
    configured: bool,
    warning_usd: Optional[str],
    refresh_seconds: int,
    status: str,
    error: str,
    provider_definition: Optional[BillingProvider] = None,
) -> Dict[str, Any]:
    payload = error_payload(
        provider=account["provider"],
        enabled=bool(account.get("enabled", True)),
        configured=configured,
        warning_usd=warning_usd,
        refresh_seconds=refresh_seconds,
        status=status,
        error=error,
        provider_definition=provider_definition,
    )
    payload.update({
        "account_id": account["id"],
        "account_label": account["label"],
    })
    return payload


def fetch_account_spend(
    account: Dict[str, Any],
    *,
    warning: Optional[Decimal],
    warning_usd: Optional[str],
    refresh_seconds: int,
    providers: Dict[str, BillingProvider],
    decrypt_secret: SecretDecryptor,
) -> Dict[str, Any]:
    provider = account["provider"]
    provider_def = providers.get(provider)
    stored_token = str(account.get("api_token") or "").strip()
    token = decrypt_secret(stored_token).strip()

    if not provider_def:
        return account_error_payload(
            account=account,
            configured=bool(token),
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="unsupported_provider",
            error=f"Cloud billing provider '{provider}' is not supported yet",
        )

    if not token:
        return account_error_payload(
            account=account,
            configured=False,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="missing_token",
            error="Cloud billing token is not configured",
            provider_definition=provider_def,
        )

    fetcher = provider_def.fetch
    normalizer = provider_def.normalize
    provider_label = provider_meta(provider, provider_def)["provider_label"]

    try:
        raw_balance = fetcher(token)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="upstream_error",
            error=f"{provider_label} billing API returned {status_code}",
            provider_definition=provider_def,
        )
    except httpx.RequestError as exc:
        return account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="request_error",
            error=str(exc) or f"{provider_label} billing API request failed",
            provider_definition=provider_def,
        )
    except Exception:
        return account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="invalid_response",
            error=f"{provider_label} billing API returned an unreadable response",
            provider_definition=provider_def,
        )

    if not isinstance(raw_balance, dict):
        return account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="invalid_response",
            error=f"{provider_label} billing API returned an unreadable response",
            provider_definition=provider_def,
        )

    normalized = normalizer(raw_balance)
    amount = normalized.pop("amount_decimal", Decimal("0"))
    model_amount = normalized.pop("model_amount_decimal", None)
    amount_scope = str(normalized.pop("amount_scope", "provider_account") or "provider_account")
    payload = {
        "ok": True,
        "enabled": True,
        "configured": True,
        "status": "ok",
        "error": "",
        "currency": "USD",
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "amount_scope": amount_scope,
        "warning_usd": warning_usd,
        "over_warning": bool(warning is not None and amount >= warning),
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        "account_id": account["id"],
        "account_label": account["label"],
        **provider_meta(provider, provider_def),
        **normalized,
    }
    if model_amount is not None:
        payload.update({
            "model_amount": _money(model_amount),
            "model_display": f"${_money(model_amount)}",
            "model_spend_scope": "model_usage",
            "model_spend_source_kind": "provider_model_billing",
            "model_spend_source_label": normalized.get("model_spend_source") or "Provider model billing",
        })
    return payload
