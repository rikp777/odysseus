"""Cloud billing status routes."""

from __future__ import annotations

import hashlib
import json
import time
from calendar import monthrange
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Callable, Dict, Optional

import httpx
from fastapi import APIRouter, Request

from core.middleware import require_admin
from src.billing_usage import get_usage_summary
from src.secret_storage import decrypt as _decrypt_secret
from src.settings import load_settings as _load_settings


_DIGITALOCEAN_BALANCE_URL = "https://api.digitalocean.com/v2/customers/my/balance"
_CACHE: Dict[str, Any] = {
    "fingerprint": "",
    "expires_at": 0.0,
    "payload": None,
}
BILLING_HISTORY_FILE = Path("data/billing_history.json")
MAX_BILLING_HISTORY_SAMPLES = 720


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _decimal_or_zero(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def _money(value: Decimal) -> str:
    return f"{value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _float_money(value: Optional[Decimal]) -> Optional[float]:
    return float(_money(value)) if value is not None else None


def _local_usage_payload(period: str = "month") -> Dict[str, Any]:
    try:
        summary = dict(get_usage_summary(period=period))
    except Exception:
        return {
            "enabled": False,
            "period": period,
            "amount": "0.000000",
            "amount_float": 0.0,
            "display": "$0.00",
            "events": 0,
            "known_cost_events": 0,
            "unknown_cost_events": 0,
            "providers": [],
            "models": [],
            "error": "Local usage ledger is unavailable",
        }
    summary.pop("amount_decimal", None)
    summary.pop("projected_decimal", None)
    return summary


def _attach_local_usage(payload: Dict[str, Any], *, period: str = "month") -> Dict[str, Any]:
    payload["local_usage"] = _local_usage_payload(period)
    return payload


def _clamp_refresh_seconds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 900
    return max(60, min(parsed, 3600))


def _token_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _fetch_digitalocean_balance(token: str) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = httpx.get(_DIGITALOCEAN_BALANCE_URL, headers=headers, timeout=10.0)
    response.raise_for_status()
    return response.json()


def _digitalocean_payload(balance: Dict[str, Any]) -> Dict[str, Any]:
    amount = _decimal_or_zero(balance.get("month_to_date_usage"))
    return {
        "amount_decimal": amount,
        "month_to_date_usage": _money(amount),
        "month_to_date_balance": str(balance.get("month_to_date_balance") or ""),
        "account_balance": str(balance.get("account_balance") or ""),
        "generated_at": balance.get("generated_at") or "",
    }


_ProviderFetch = Callable[[str], Dict[str, Any]]
_ProviderNormalize = Callable[[Dict[str, Any]], Dict[str, Any]]

_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "digitalocean": {
        "label": "DigitalOcean",
        "short_label": "DO",
        "token_hint": "DigitalOcean token with billing:read",
        "fetch": _fetch_digitalocean_balance,
        "normalize": _digitalocean_payload,
    },
}


def _provider_meta(provider: str) -> Dict[str, str]:
    definition = _PROVIDERS.get(provider) or {}
    label = definition.get("label") or provider or "Cloud provider"
    return {
        "provider": provider,
        "provider_label": label,
        "provider_short_label": definition.get("short_label") or label[:2].upper(),
        "provider_token_hint": definition.get("token_hint") or "Provider billing API token",
    }


def _normalized_provider(value: Any) -> str:
    provider = str(value or "digitalocean").strip().lower()
    return provider or "digitalocean"


def _read_billing_history() -> list[Dict[str, Any]]:
    try:
        with open(BILLING_HISTORY_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def _write_billing_history(samples: list[Dict[str, Any]]) -> None:
    from core.atomic_io import atomic_write_json

    atomic_write_json(str(BILLING_HISTORY_FILE), samples[-MAX_BILLING_HISTORY_SAMPLES:], indent=2)


def _account_history_snapshot(account: Dict[str, Any]) -> Dict[str, Any]:
    amount = _decimal_or_none(account.get("amount"))
    return {
        "account_id": account.get("account_id") or account.get("id") or "",
        "account_label": account.get("account_label") or account.get("label") or "",
        "provider": account.get("provider") or "",
        "provider_label": account.get("provider_label") or "",
        "amount": _money(amount or Decimal("0")),
        "display": f"${_money(amount or Decimal('0'))}",
        "ok": bool(account.get("ok", False)),
        "status": account.get("status") or "",
    }


def _billing_scope(forced_provider: Optional[str] = None) -> str:
    return _normalized_provider(forced_provider) if forced_provider else "all"


def _record_billing_sample(status: Dict[str, Any], *, forced_provider: Optional[str] = None) -> None:
    amount = _decimal_or_none(status.get("amount"))
    if amount is None:
        return

    now = datetime.now(timezone.utc)
    scope = _billing_scope(forced_provider)
    sample = {
        "timestamp": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "month": now.strftime("%Y-%m"),
        "scope": scope,
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "currency": status.get("currency") or "USD",
        "provider": status.get("provider") or "multiple",
        "provider_label": status.get("provider_label") or "Cloud",
        "accounts": [_account_history_snapshot(item) for item in status.get("accounts", []) if isinstance(item, dict)],
    }

    samples = _read_billing_history()
    if (
        samples
        and samples[-1].get("month") == sample["month"]
        and samples[-1].get("scope") == sample["scope"]
        and samples[-1].get("amount") == sample["amount"]
    ):
        samples[-1] = sample
    else:
        samples.append(sample)
    _write_billing_history(samples)


def _history_for_current_month(*, scope: str, now: Optional[datetime] = None) -> list[Dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    month = current.strftime("%Y-%m")
    points = []
    for item in _read_billing_history():
        if item.get("month") != month or item.get("scope") != scope:
            continue
        amount = _decimal_or_none(item.get("amount"))
        if amount is None:
            continue
        points.append({
            "timestamp": item.get("timestamp") or "",
            "amount": _float_money(amount),
            "display": f"${_money(amount)}",
        })
    return points


def _chart_accounts(status: Dict[str, Any]) -> list[Dict[str, Any]]:
    accounts = []
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    group_by = str(status.get("group_by") or "provider").lower()
    if local_usage and local_usage.get("enabled"):
        if group_by == "model":
            for item in local_usage.get("models", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                accounts.append({
                    "id": item.get("id") or item.get("label") or "model",
                    "label": item.get("label") or item.get("id") or "Model",
                    "provider": "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": f"{item.get('total_tokens', 0)} tokens",
                    "error": "",
                })
        elif group_by == "provider":
            for item in local_usage.get("providers", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                accounts.append({
                    "id": "usage-" + str(item.get("id") or item.get("label") or "provider"),
                    "label": str(item.get("label") or item.get("id") or "Provider") + " model usage",
                    "provider": item.get("id") or "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": f"{item.get('total_tokens', 0)} tokens",
                    "error": "",
                })
        elif local_usage.get("events") or not status.get("accounts"):
            amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
            accounts.append({
                "id": "local-model-usage",
                "label": "Tracked model usage",
                "provider": "local_usage",
                "provider_label": "Local usage",
                "amount": _float_money(amount) or 0.0,
                "display": local_usage.get("display") or f"${_money(amount)}",
                "ok": True,
                "status": f"{local_usage.get('total_tokens', 0)} tokens",
                "error": "",
            })
    for item in status.get("accounts", []):
        if not isinstance(item, dict):
            continue
        amount = _decimal_or_none(item.get("amount")) or Decimal("0")
        label = str(item.get("account_label") or item.get("label") or item.get("provider_label") or "Cloud").strip()
        provider_label = str(item.get("provider_label") or item.get("provider") or "").strip()
        accounts.append({
            "id": item.get("account_id") or item.get("id") or "",
            "label": label or "Cloud",
            "provider": item.get("provider") or "",
            "provider_label": provider_label,
            "amount": _float_money(amount) or 0.0,
            "display": f"${_money(amount)}",
            "ok": bool(item.get("ok", False)),
            "status": item.get("status") or "",
            "error": item.get("error") or "",
        })

    if not accounts and status.get("amount") is not None:
        amount = _decimal_or_none(status.get("amount")) or Decimal("0")
        accounts.append({
            "id": status.get("provider") or "cloud",
            "label": status.get("provider_label") or "Cloud",
            "provider": status.get("provider") or "",
            "provider_label": status.get("provider_label") or "Cloud",
            "amount": _float_money(amount) or 0.0,
            "display": f"${_money(amount)}",
            "ok": bool(status.get("ok", False)),
            "status": status.get("status") or "",
            "error": status.get("error") or "",
        })
    return accounts


def build_spending_graph_payload(
    status: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    period = str(status.get("period") or "month")
    days_in_month = monthrange(current.year, current.month)[1]
    elapsed_days = max(1, current.day)
    amount = _decimal_or_none(status.get("amount"))
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    if amount is None and local_usage:
        amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
    amount = amount or Decimal("0")
    warning = _decimal_or_none(status.get("warning_usd"))
    limit = _decimal_or_none(status.get("limit_usd"))
    projected = (amount / Decimal(elapsed_days)) * Decimal(days_in_month) if period == "month" and amount > 0 else amount
    history = _history_for_current_month(scope=_billing_scope(forced_provider), now=current)

    return {
        "version": 1,
        "kind": "billing-spend",
        "title": "Model Spend" if status.get("provider") == "local_usage" else "Cloud Spend",
        "subtitle": "Today" if period == "day" else f"{current.strftime('%B %Y')} month-to-date",
        "status": status.get("status") or "",
        "ok": bool(status.get("ok", False)),
        "enabled": bool(status.get("enabled", False)),
        "configured": bool(status.get("configured", False)),
        "currency": status.get("currency") or "USD",
        "total": _float_money(amount) or 0.0,
        "total_display": f"${_money(amount)}",
        "warning": _float_money(warning),
        "warning_display": f"${_money(warning)}" if warning is not None else "",
        "limit": _float_money(limit),
        "limit_display": f"${_money(limit)}" if limit is not None else "",
        "projected": _float_money(projected) or 0.0,
        "projected_display": f"${_money(projected)}",
        "remaining_limit": _float_money(max(limit - amount, Decimal("0"))) if limit is not None else None,
        "remaining_limit_display": f"${_money(max(limit - amount, Decimal('0')))}" if limit is not None else "",
        "days_elapsed": elapsed_days,
        "days_in_month": days_in_month,
        "updated_at": status.get("updated_at") or _utc_now_iso(),
        "cached": bool(status.get("cached", False)),
        "provider_label": status.get("provider_label") or "Cloud",
        "provider_short_label": status.get("provider_short_label") or "ALL",
        "period": period,
        "group_by": status.get("group_by") or "provider",
        "local_usage": local_usage or {},
        "accounts": _chart_accounts(status),
        "history": history,
        "notice": status.get("error") or "",
    }


def billing_chart_markdown(chart: Dict[str, Any]) -> str:
    payload = json.dumps(chart, ensure_ascii=False, separators=(",", ":"))
    return f"```billing-chart\n{payload}\n```"


def _account_id(account: Dict[str, Any], idx: int) -> str:
    raw = str(account.get("id") or "").strip()
    if raw:
        return raw[:80]
    provider = _normalized_provider(account.get("provider"))
    label = str(account.get("label") or "").strip()
    digest = hashlib.sha1(f"{provider}:{label}:{idx}".encode("utf-8")).hexdigest()[:10]
    return f"{provider}-{digest}"


def _account_label(provider: str, account: Dict[str, Any]) -> str:
    label = str(account.get("label") or "").strip()
    return label or _provider_meta(provider)["provider_label"]


def _billing_accounts(settings: Dict[str, Any]) -> list[Dict[str, Any]]:
    raw_accounts = settings.get("cloud_billing_accounts")
    if isinstance(raw_accounts, list):
        accounts = []
        for idx, item in enumerate(raw_accounts):
            if not isinstance(item, dict):
                continue
            provider = _normalized_provider(item.get("provider"))
            accounts.append({
                "id": _account_id(item, idx),
                "provider": provider,
                "label": _account_label(provider, item),
                "enabled": bool(item.get("enabled", True)),
                "api_token": str(item.get("api_token") or "").strip(),
            })
        return accounts

    legacy_token = str(settings.get("cloud_billing_api_token") or "").strip()
    legacy_provider = _normalized_provider(settings.get("cloud_billing_provider"))
    if legacy_token:
        return [{
            "id": legacy_provider,
            "provider": legacy_provider,
            "label": _provider_meta(legacy_provider)["provider_label"],
            "enabled": True,
            "api_token": legacy_token,
        }]
    return []


def _error_payload(
    *,
    provider: str,
    enabled: bool,
    configured: bool,
    warning_usd: Optional[str],
    refresh_seconds: int,
    status: str,
    error: str,
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
        **_provider_meta(provider),
    }


def _empty_payload(
    *,
    enabled: bool,
    configured: bool,
    warning_usd: Optional[str],
    limit_usd: Optional[str],
    refresh_seconds: int,
    status: str,
    error: str,
    accounts: Optional[list[Dict[str, Any]]] = None,
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
        "limit_usd": limit_usd,
        "over_warning": False,
        "over_limit": False,
        "limit_check_blocked": False,
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        "provider": "multiple",
        "provider_label": "Cloud",
        "provider_short_label": "ALL",
        "provider_token_hint": "Provider billing API token",
        "accounts": accounts or [],
    }


def _local_only_payload(
    *,
    period: str,
    warning_usd: Optional[str],
    limit_usd: Optional[str],
    refresh_seconds: int,
) -> Dict[str, Any]:
    local_usage = _local_usage_payload(period)
    amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
    warning = _decimal_or_none(warning_usd)
    limit = _decimal_or_none(limit_usd)
    return {
        "ok": True,
        "enabled": True,
        "configured": True,
        "status": "ok",
        "error": "",
        "currency": "USD",
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "warning_usd": warning_usd,
        "limit_usd": limit_usd,
        "over_warning": bool(warning is not None and amount >= warning),
        "over_limit": bool(limit is not None and amount >= limit),
        "limit_check_blocked": False,
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        "provider": "local_usage",
        "provider_label": "Local usage",
        "provider_short_label": "USG",
        "provider_token_hint": "Local model usage ledger",
        "accounts": [],
        "period": period,
        "local_usage": local_usage,
    }


def _account_error_payload(
    *,
    account: Dict[str, Any],
    configured: bool,
    warning_usd: Optional[str],
    refresh_seconds: int,
    status: str,
    error: str,
) -> Dict[str, Any]:
    provider = account["provider"]
    payload = _error_payload(
        provider=provider,
        enabled=bool(account.get("enabled", True)),
        configured=configured,
        warning_usd=warning_usd,
        refresh_seconds=refresh_seconds,
        status=status,
        error=error,
    )
    payload.update({
        "account_id": account["id"],
        "account_label": account["label"],
    })
    return payload


def _fetch_account_spend(
    account: Dict[str, Any],
    *,
    warning: Optional[Decimal],
    warning_usd: Optional[str],
    refresh_seconds: int,
) -> Dict[str, Any]:
    provider = account["provider"]
    provider_def = _PROVIDERS.get(provider)
    stored_token = str(account.get("api_token") or "").strip()
    token = _decrypt_secret(stored_token).strip()

    if not provider_def:
        return _account_error_payload(
            account=account,
            configured=bool(token),
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="unsupported_provider",
            error=f"Cloud billing provider '{provider}' is not supported yet",
        )

    if not token:
        return _account_error_payload(
            account=account,
            configured=False,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="missing_token",
            error="Cloud billing token is not configured",
        )

    fetcher: _ProviderFetch = provider_def["fetch"]
    normalizer: _ProviderNormalize = provider_def["normalize"]
    provider_label = _provider_meta(provider)["provider_label"]

    try:
        raw_balance = fetcher(token)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        return _account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="upstream_error",
            error=f"{provider_label} billing API returned {status_code}",
        )
    except httpx.RequestError as exc:
        return _account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="request_error",
            error=str(exc) or f"{provider_label} billing API request failed",
        )
    except Exception:
        return _account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="invalid_response",
            error=f"{provider_label} billing API returned an unreadable response",
        )

    if not isinstance(raw_balance, dict):
        return _account_error_payload(
            account=account,
            configured=True,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
            status="invalid_response",
            error=f"{provider_label} billing API returned an unreadable response",
        )

    normalized = normalizer(raw_balance)
    amount = normalized.pop("amount_decimal", Decimal("0"))
    payload = {
        "ok": True,
        "enabled": True,
        "configured": True,
        "status": "ok",
        "error": "",
        "currency": "USD",
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "warning_usd": warning_usd,
        "over_warning": bool(warning is not None and amount >= warning),
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        "account_id": account["id"],
        "account_label": account["label"],
        **_provider_meta(provider),
        **normalized,
    }
    return payload


def _monthly_spend(request: Request, *, refresh: bool, forced_provider: Optional[str] = None) -> Dict[str, Any]:
    require_admin(request)
    return get_monthly_spend_status(refresh=refresh, forced_provider=forced_provider)


def get_monthly_spend_status(*, refresh: bool = False, forced_provider: Optional[str] = None) -> Dict[str, Any]:
    settings = _load_settings()
    enabled = bool(settings.get("cloud_billing_enabled"))
    refresh_seconds = _clamp_refresh_seconds(settings.get("cloud_billing_refresh_seconds"))
    warning_raw = str(settings.get("cloud_billing_monthly_warning_usd") or "").strip()
    warning = _decimal_or_zero(warning_raw) if warning_raw else None
    warning_usd = _money(warning) if warning is not None else None
    limit_raw = str(settings.get("cloud_billing_monthly_limit_usd") or "").strip()
    limit = _decimal_or_zero(limit_raw) if limit_raw else None
    limit_usd = _money(limit) if limit is not None else None
    accounts = _billing_accounts(settings)
    if forced_provider:
        wanted = _normalized_provider(forced_provider)
        accounts = [account for account in accounts if account["provider"] == wanted]

    visible_accounts = [account for account in accounts if account.get("enabled", True)]
    account_summaries = [
        {
            "account_id": account["id"],
            "account_label": account["label"],
            **_provider_meta(account["provider"]),
            "enabled": bool(account.get("enabled", True)),
            "configured": bool(str(account.get("api_token") or "").strip()),
        }
        for account in accounts
    ]

    if not enabled:
        return _attach_local_usage(_empty_payload(
            enabled=False,
            configured=any(item["configured"] for item in account_summaries),
            warning_usd=warning_usd,
            limit_usd=limit_usd,
            refresh_seconds=refresh_seconds,
            status="disabled",
            error="Cloud billing display is disabled",
            accounts=account_summaries,
        ))

    if not visible_accounts:
        if not forced_provider and settings.get("cloud_billing_usage_ledger_enabled") is not False:
            return _local_only_payload(
                period="month",
                warning_usd=warning_usd,
                limit_usd=limit_usd,
                refresh_seconds=refresh_seconds,
            )
        return _attach_local_usage(_empty_payload(
            enabled=True,
            configured=False,
            warning_usd=warning_usd,
            limit_usd=limit_usd,
            refresh_seconds=refresh_seconds,
            status="missing_account",
            error="No enabled cloud billing accounts are configured",
            accounts=account_summaries,
        ))

    fingerprint_parts = [
        str(enabled),
        warning_usd or "",
        limit_usd or "",
        str(refresh_seconds),
        forced_provider or "",
    ]
    for account in visible_accounts:
        fingerprint_parts.extend([
            account["id"],
            account["provider"],
            account["label"],
            _decrypt_secret(str(account.get("api_token") or "").strip()),
        ])
    fingerprint = _token_fingerprint("\n".join(fingerprint_parts))
    now = time.time()
    if (
        not refresh
        and _CACHE.get("fingerprint") == fingerprint
        and _CACHE.get("payload")
        and float(_CACHE.get("expires_at") or 0) > now
    ):
        payload = dict(_CACHE["payload"])
        payload["accounts"] = [dict(item) for item in payload.get("accounts", [])]
        payload["cached"] = True
        _attach_local_usage(payload)
        return payload

    account_results = [
        _fetch_account_spend(
            account,
            warning=warning,
            warning_usd=warning_usd,
            refresh_seconds=refresh_seconds,
        )
        for account in visible_accounts
    ]
    total = sum((_decimal_or_zero(item.get("amount")) for item in account_results if item.get("ok")), Decimal("0"))
    configured = any(item.get("configured") for item in account_results)
    any_errors = any(not item.get("ok") for item in account_results)
    any_success = any(item.get("ok") for item in account_results)

    if not configured:
        status = "missing_token"
        error = "No enabled cloud billing accounts have a billing token"
    elif any_errors and any_success:
        status = "partial_error"
        error = "One or more cloud billing providers could not be refreshed"
    elif any_errors:
        status = "provider_error"
        error = "Cloud billing providers could not be refreshed"
    else:
        status = "ok"
        error = ""

    payload = {
        "ok": status == "ok",
        "enabled": True,
        "configured": configured,
        "status": status,
        "error": error,
        "currency": "USD",
        "amount": _money(total) if any_success else None,
        "display": f"${_money(total)}" if any_success else "",
        "warning_usd": warning_usd,
        "limit_usd": limit_usd,
        "over_warning": bool(warning is not None and total >= warning),
        "over_limit": bool(limit is not None and any_success and total >= limit),
        "limit_check_blocked": bool(limit is not None and configured and not any_success),
        "refresh_seconds": refresh_seconds,
        "updated_at": _utc_now_iso(),
        "cached": False,
        "provider": "multiple",
        "provider_label": "Cloud",
        "provider_short_label": "ALL" if len(visible_accounts) > 1 else (account_results[0].get("provider_short_label") if account_results else "ALL"),
        "provider_token_hint": "Provider billing API token",
        "accounts": account_results,
    }
    _attach_local_usage(payload)
    _CACHE.update({
        "fingerprint": fingerprint,
        "expires_at": now + refresh_seconds,
        "payload": dict(payload),
    })
    return payload


def get_spending_graph_status(
    *,
    refresh: bool = False,
    forced_provider: Optional[str] = None,
    period: str = "month",
    group_by: str = "provider",
) -> Dict[str, Any]:
    normalized_period = "day" if str(period or "").lower() in {"day", "today"} else "month"
    normalized_group = str(group_by or "provider").strip().lower()
    if normalized_group not in {"provider", "model", "summary"}:
        normalized_group = "provider"

    if normalized_period == "day":
        settings = _load_settings()
        status = _local_only_payload(
            period="day",
            warning_usd=None,
            limit_usd=str(settings.get("cloud_billing_daily_limit_usd") or "").strip() or None,
            refresh_seconds=_clamp_refresh_seconds(settings.get("cloud_billing_refresh_seconds")),
        )
    else:
        status = get_monthly_spend_status(refresh=refresh, forced_provider=forced_provider)
    status["period"] = normalized_period
    status["group_by"] = normalized_group
    if normalized_period == "month" and status.get("provider") != "local_usage" and status.get("amount") is not None:
        _record_billing_sample(status, forced_provider=forced_provider)
    chart = build_spending_graph_payload(status, forced_provider=forced_provider)
    return {
        **status,
        "chart": chart,
        "markdown": billing_chart_markdown(chart),
    }


def setup_billing_routes() -> APIRouter:
    router = APIRouter(prefix="/api/billing", tags=["billing"])

    @router.get("/monthly-spend")
    def monthly_spend(request: Request, refresh: bool = False) -> Dict[str, Any]:
        return _monthly_spend(request, refresh=refresh)

    @router.get("/spending-graph")
    def spending_graph(
        request: Request,
        refresh: bool = False,
        provider: str = "",
        period: str = "month",
        group_by: str = "provider",
    ) -> Dict[str, Any]:
        require_admin(request)
        forced_provider = provider.strip() if provider else None
        return get_spending_graph_status(
            refresh=refresh,
            forced_provider=forced_provider,
            period=period,
            group_by=group_by,
        )

    @router.get("/usage-summary")
    def usage_summary(request: Request, period: str = "month") -> Dict[str, Any]:
        require_admin(request)
        return _local_usage_payload(period)

    @router.get("/{provider}/monthly-spend")
    def provider_monthly_spend(provider: str, request: Request, refresh: bool = False) -> Dict[str, Any]:
        return _monthly_spend(request, refresh=refresh, forced_provider=provider)

    return router
