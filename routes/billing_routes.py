"""Cloud billing status routes."""

from __future__ import annotations

import hashlib
import json
import re
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
_DIGITALOCEAN_ACCOUNT_URL = "https://api.digitalocean.com/v2/account"
_DIGITALOCEAN_BILLING_INSIGHTS_URL = "https://api.digitalocean.com/v2/billing/{account_urn}/insights/{start_date}/{end_date}"
_DIGITALOCEAN_MODEL_RE = re.compile(
    r"^(?P<model>.+?)\s+(?:Cache\s+Read\s+Input|Input|Output)\s+tokens\b",
    re.IGNORECASE,
)
_CACHE: Dict[str, Any] = {
    "fingerprint": "",
    "expires_at": 0.0,
    "payload": None,
}
BILLING_HISTORY_FILE = Path("data/billing_history.json")
MAX_BILLING_HISTORY_SAMPLES = 720
_BILLING_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


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


def _int_or_zero(value: Any) -> int:
    try:
        return max(int(value or 0), 0)
    except (TypeError, ValueError):
        return 0


def _usage_breakdown(source: Any) -> Dict[str, Any]:
    if not isinstance(source, dict):
        return {}
    events = _int_or_zero(source.get("events"))
    input_tokens = _int_or_zero(source.get("input_tokens"))
    output_tokens = _int_or_zero(source.get("output_tokens"))
    total_tokens = _int_or_zero(source.get("total_tokens")) or input_tokens + output_tokens
    known_cost_events = _int_or_zero(source.get("known_cost_events"))
    raw_unknown = source.get("unknown_cost_events")
    unknown_cost_events = (
        _int_or_zero(raw_unknown)
        if raw_unknown is not None
        else max(events - known_cost_events, 0)
    )
    if not any((events, input_tokens, output_tokens, total_tokens, known_cost_events, unknown_cost_events)):
        return {}
    return {
        "events": events,
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "known_cost_events": known_cost_events,
        "unknown_cost_events": unknown_cost_events,
        "priced_percent": round((known_cost_events / events) * 100, 1) if events else None,
    }


def _usage_status(usage: Dict[str, Any]) -> str:
    if not usage:
        return ""
    parts = []
    total_tokens = _int_or_zero(usage.get("total_tokens"))
    events = _int_or_zero(usage.get("events"))
    unknown_cost_events = _int_or_zero(usage.get("unknown_cost_events"))
    if total_tokens:
        parts.append(f"{total_tokens} tokens")
    if events:
        parts.append(f"{events} model calls")
    if unknown_cost_events:
        parts.append(f"{unknown_cost_events} unpriced")
    return " | ".join(parts)


def _chart_usage_payload(local_usage: Any) -> Dict[str, Any]:
    if not isinstance(local_usage, dict):
        return {}
    usage = _usage_breakdown(local_usage)
    if not usage:
        return {}
    usage.update({
        "enabled": bool(local_usage.get("enabled", False)),
        "period": local_usage.get("period") or "",
        "currency": local_usage.get("currency") or "USD",
        "amount": local_usage.get("amount_float", local_usage.get("amount")),
        "amount_display": local_usage.get("display") or "",
        "projected": local_usage.get("projected"),
        "projected_display": local_usage.get("projected_display") or "",
        "source": "local_model_usage_ledger",
        "source_kind": "usage_ledger",
        "source_label": "Usage ledger",
    })
    return usage


def _chart_source_note(status: Dict[str, Any], usage: Dict[str, Any]) -> str:
    provider_accounts = status.get("accounts", [])
    has_provider_billing = any(
        isinstance(item, dict) and item.get("amount") is not None
        for item in provider_accounts
    )
    has_usage_estimates = bool(usage)
    if status.get("spend_source") == "provider_model_billing":
        return "Model spend from provider billing insights"
    if status.get("spend_source") == "usage_ledger":
        return "Model spend from usage ledger estimates"
    if has_provider_billing and has_usage_estimates:
        return "Account total from provider billing; usage rows are estimates"
    if has_usage_estimates:
        return "Model spend from usage ledger estimates"
    if has_provider_billing:
        return "Account total from provider billing"
    return ""


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


def _local_usage_amount(local_usage: Any, *, forced_provider: Optional[str] = None) -> Optional[Decimal]:
    if not isinstance(local_usage, dict) or local_usage.get("enabled") is False:
        return None
    if forced_provider:
        wanted = _normalized_provider(forced_provider)
        for item in local_usage.get("providers", []):
            if not isinstance(item, dict):
                continue
            keys = {
                str(item.get("id") or "").strip().lower(),
                str(item.get("label") or "").strip().lower(),
            }
            if wanted in keys:
                return _decimal_or_none(item.get("amount")) or Decimal("0")
        return Decimal("0")
    return _decimal_or_none(local_usage.get("amount")) or Decimal("0")


def _local_usage_provider_meta(
    local_usage: Any,
    *,
    forced_provider: Optional[str] = None,
) -> Dict[str, str]:
    if forced_provider:
        meta = _provider_meta(_normalized_provider(forced_provider))
        return {
            "provider": _normalized_provider(forced_provider),
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
        meta = _provider_meta(unique[0])
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


def _provider_model_spend_amount(
    payload: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
) -> Optional[Decimal]:
    total = Decimal("0")
    found = False
    wanted = _normalized_provider(forced_provider) if forced_provider else ""
    for item in payload.get("accounts", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip().lower()
        if wanted and provider != wanted:
            continue
        amount = _decimal_or_none(item.get("model_amount"))
        if amount is None:
            continue
        total += amount
        found = True
    return total if found else None


def _provider_model_spend_meta(
    payload: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
) -> Dict[str, str]:
    wanted = _normalized_provider(forced_provider) if forced_provider else ""
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
        meta = _provider_meta(unique[0])
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


def _apply_primary_spend_source(
    payload: Dict[str, Any],
    *,
    settings: Dict[str, Any],
    warning: Optional[Decimal],
    limit: Optional[Decimal],
    forced_provider: Optional[str] = None,
) -> Dict[str, Any]:
    provider_amount = _decimal_or_none(payload.get("amount"))
    if provider_amount is not None and payload.get("provider") != "local_usage":
        payload.update({
            "provider_amount": _money(provider_amount),
            "provider_display": f"${_money(provider_amount)}",
            "provider_spend_scope": "account",
            "provider_source_label": "Provider billing",
        })

    provider_model_amount = _provider_model_spend_amount(payload, forced_provider=forced_provider)
    if provider_model_amount is not None:
        payload.update({
            "ok": True,
            "configured": True,
            "status": "ok",
            "error": "",
            "amount": _money(provider_model_amount),
            "display": f"${_money(provider_model_amount)}",
            "over_warning": bool(warning is not None and provider_model_amount >= warning),
            "over_limit": bool(limit is not None and provider_model_amount >= limit),
            "limit_check_blocked": False,
            "spend_source": "provider_model_billing",
            "spend_scope": "model_usage",
            "source_label": "Provider model billing",
            **_provider_model_spend_meta(payload, forced_provider=forced_provider),
        })
        return payload

    if settings.get("cloud_billing_usage_ledger_enabled") is False:
        payload.setdefault("spend_source", "provider_billing")
        payload.setdefault("spend_scope", "provider_account")
        payload.setdefault("source_label", "Provider billing")
        return payload

    amount = _local_usage_amount(payload.get("local_usage"), forced_provider=forced_provider)
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
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "over_warning": bool(warning is not None and amount >= warning),
        "over_limit": bool(limit is not None and amount >= limit),
        "limit_check_blocked": False,
        "spend_source": "usage_ledger",
        "spend_scope": "model_usage",
        "source_label": "Usage ledger",
        **_local_usage_provider_meta(payload.get("local_usage"), forced_provider=forced_provider),
    })
    if provider_status and provider_status != "ok":
        payload["provider_status"] = provider_status
    if provider_error:
        payload["provider_error"] = provider_error
    return payload


def _clamp_refresh_seconds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 900
    return max(60, min(parsed, 3600))


def _token_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _digitalocean_account_urn(headers: Dict[str, str]) -> str:
    response = httpx.get(_DIGITALOCEAN_ACCOUNT_URL, headers=headers, timeout=10.0)
    response.raise_for_status()
    account = response.json().get("account") or {}
    team = account.get("team") or {}
    team_uuid = str(team.get("uuid") or "").strip()
    if team_uuid:
        return f"do:team:{team_uuid}"
    account_uuid = str(account.get("uuid") or "").strip()
    return f"do:team:{account_uuid}" if account_uuid else ""


def _digitalocean_month_range() -> tuple[str, str]:
    today = datetime.now(timezone.utc).date()
    return today.replace(day=1).isoformat(), today.isoformat()


def _digitalocean_model_label(description: str) -> str:
    match = _DIGITALOCEAN_MODEL_RE.search(description or "")
    return (match.group("model") if match else description or "DigitalOcean model").strip()


def _is_digitalocean_inference_item(item: Dict[str, Any]) -> bool:
    text = " ".join(
        str(item.get(key) or "")
        for key in ("description", "group_description", "product", "sku")
    ).lower()
    return "serverless inference" in text or "genai" in text or "1-ai-si" in text


def _digitalocean_inference_summary(points: list[Dict[str, Any]]) -> Dict[str, Any]:
    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    models: Dict[str, Dict[str, Any]] = {}

    for point in points:
        if not isinstance(point, dict) or not _is_digitalocean_inference_item(point):
            continue
        amount = _decimal_or_zero(point.get("total_amount"))
        if amount <= 0:
            continue
        description = str(point.get("description") or "DigitalOcean inference").strip()
        model_label = _digitalocean_model_label(description)
        total += amount
        items.append({
            "id": str(point.get("sku") or description).strip(),
            "label": description,
            "model": model_label,
            "amount": _money(amount),
            "display": f"${_money(amount)}",
            "start_date": str(point.get("start_date") or ""),
            "group_description": str(point.get("group_description") or ""),
            "sku": str(point.get("sku") or ""),
        })

        model_key = model_label.lower()
        model = models.setdefault(model_key, {
            "id": model_key,
            "label": model_label,
            "amount_decimal": Decimal("0"),
            "events": 0,
        })
        model["amount_decimal"] += amount
        model["events"] += 1

    model_rows = []
    for model in models.values():
        amount = model.pop("amount_decimal")
        model_rows.append({
            **model,
            "amount": _money(amount),
            "display": f"${_money(amount)}",
        })
    model_rows.sort(key=lambda item: _decimal_or_zero(item["amount"]), reverse=True)

    return {
        "amount_decimal": total,
        "amount": _money(total),
        "display": f"${_money(total)}",
        "provider": "digitalocean",
        "provider_label": "DigitalOcean",
        "label": "DigitalOcean GenAI Serverless Inference",
        "source_kind": "provider_model_billing",
        "source_label": "Provider model billing",
        "items": items,
        "models": model_rows,
    }


def _fetch_digitalocean_inference_spend(headers: Dict[str, str]) -> Dict[str, Any]:
    account_urn = _digitalocean_account_urn(headers)
    if not account_urn:
        return {}
    start_date, end_date = _digitalocean_month_range()
    points: list[Dict[str, Any]] = []
    page = 1
    total_pages = 1
    while page <= total_pages:
        url = _DIGITALOCEAN_BILLING_INSIGHTS_URL.format(
            account_urn=account_urn,
            start_date=start_date,
            end_date=end_date,
        )
        response = httpx.get(
            url,
            headers=headers,
            params={"per_page": 200, "page": page},
            timeout=15.0,
        )
        response.raise_for_status()
        data = response.json()
        raw_points = data.get("data_points") or data.get("data") or []
        if isinstance(raw_points, list):
            points.extend(item for item in raw_points if isinstance(item, dict))
        total_pages = max(_int_or_zero(data.get("total_pages")) or 1, 1)
        page += 1
    return _digitalocean_inference_summary(points)


def _fetch_digitalocean_balance(token: str) -> Dict[str, Any]:
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    response = httpx.get(_DIGITALOCEAN_BALANCE_URL, headers=headers, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    try:
        payload["_odysseus_model_billing"] = _fetch_digitalocean_inference_spend(headers)
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        payload["_odysseus_model_billing_error"] = f"DigitalOcean billing insights returned {status_code}"
    except httpx.RequestError as exc:
        payload["_odysseus_model_billing_error"] = str(exc) or "DigitalOcean billing insights request failed"
    except Exception:
        payload["_odysseus_model_billing_error"] = "DigitalOcean billing insights returned an unreadable response"
    return payload


def _model_billing_amount(summary: Any) -> Optional[Decimal]:
    if not isinstance(summary, dict):
        return None
    return _decimal_or_none(summary.get("amount_decimal") or summary.get("amount"))


def _digitalocean_payload(balance: Dict[str, Any]) -> Dict[str, Any]:
    amount = _decimal_or_zero(balance.get("month_to_date_usage"))
    payload = {
        "amount_decimal": amount,
        "month_to_date_usage": _money(amount),
        "month_to_date_balance": str(balance.get("month_to_date_balance") or ""),
        "account_balance": str(balance.get("account_balance") or ""),
        "generated_at": balance.get("generated_at") or "",
    }
    model_billing = balance.get("_odysseus_model_billing")
    model_amount = _model_billing_amount(model_billing)
    if model_amount is not None:
        payload.update({
            "model_amount_decimal": model_amount,
            "model_display": f"${_money(model_amount)}",
            "model_spend_label": str(model_billing.get("label") or "DigitalOcean GenAI Serverless Inference"),
            "model_spend_source": str(model_billing.get("source_label") or "Provider model billing"),
            "model_spend_items": model_billing.get("items") if isinstance(model_billing.get("items"), list) else [],
            "model_spend_models": model_billing.get("models") if isinstance(model_billing.get("models"), list) else [],
        })
    if balance.get("_odysseus_model_billing_error"):
        payload["model_spend_error"] = str(balance.get("_odysseus_model_billing_error") or "")
    return payload


_ProviderFetch = Callable[[str], Dict[str, Any]]
_ProviderNormalize = Callable[[Dict[str, Any]], Dict[str, Any]]

_PROVIDERS: Dict[str, Dict[str, Any]] = {
    "digitalocean": {
        "label": "DigitalOcean",
        "short_label": "DO",
        "token_hint": "DigitalOcean token with billing:read and account:read",
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
    snapshot = {
        "account_id": account.get("account_id") or account.get("id") or "",
        "account_label": account.get("account_label") or account.get("label") or "",
        "provider": account.get("provider") or "",
        "provider_label": account.get("provider_label") or "",
        "amount": _money(amount or Decimal("0")),
        "display": f"${_money(amount or Decimal('0'))}",
        "ok": bool(account.get("ok", False)),
        "status": account.get("status") or "",
    }
    model_amount = _decimal_or_none(account.get("model_amount"))
    if model_amount is not None:
        snapshot.update({
            "model_amount": _money(model_amount),
            "model_display": account.get("model_display") or f"${_money(model_amount)}",
            "model_spend_label": account.get("model_spend_label") or "",
            "model_spend_source_label": account.get("model_spend_source_label")
            or account.get("model_spend_source")
            or "",
            "model_spend_models": account.get("model_spend_models") if isinstance(account.get("model_spend_models"), list) else [],
        })
    return snapshot


def _billing_scope(forced_provider: Optional[str] = None) -> str:
    return _normalized_provider(forced_provider) if forced_provider else "all"


def _billing_month(value: Any = "", *, now: Optional[datetime] = None) -> str:
    raw = str(value or "").strip()
    if _BILLING_MONTH_RE.fullmatch(raw):
        return raw
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y-%m")


def _billing_month_datetime(month: str) -> datetime:
    normalized = _billing_month(month)
    return datetime(int(normalized[:4]), int(normalized[5:7]), 1, tzinfo=timezone.utc)


def _billing_month_label(month: str) -> str:
    return _billing_month_datetime(month).strftime("%B %Y")


def _shift_billing_month(month: str, offset: int) -> str:
    reference = _billing_month_datetime(month)
    month_index = (reference.year * 12) + reference.month - 1 + offset
    year = month_index // 12
    shifted_month = (month_index % 12) + 1
    return f"{year:04d}-{shifted_month:02d}"


def _history_spend_source(status: Dict[str, Any]) -> str:
    return str(status.get("spend_source") or "provider_billing").strip().lower() or "provider_billing"


def _history_spend_scope(status: Dict[str, Any]) -> str:
    return str(status.get("spend_scope") or "provider_account").strip().lower() or "provider_account"


def _normalized_history_spend_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    return source if source in {"provider_billing", "provider_model_billing", "usage_ledger"} else "provider_billing"


def _normalized_history_spend_scope(value: Any) -> str:
    scope = str(value or "").strip().lower()
    return scope if scope in {"provider_account", "model_usage"} else "provider_account"


def _history_source_label(spend_source: str) -> str:
    if spend_source == "provider_model_billing":
        return "Provider model billing"
    if spend_source == "usage_ledger":
        return "Usage ledger"
    return "Provider billing"


def _history_item_matches_series(
    item: Dict[str, Any],
    *,
    spend_source: str,
    spend_scope: str,
) -> bool:
    item_scope = str(item.get("spend_scope") or "").strip().lower()
    item_source = str(item.get("spend_source") or "").strip().lower()
    if not item_scope and not item_source:
        legacy_label = " ".join(
            str(item.get(key) or "")
            for key in ("provider_label", "source_label", "label")
        ).lower()
        if "model" in legacy_label:
            return (
                spend_scope == "model_usage"
                and spend_source in {"provider_model_billing", "usage_ledger"}
            )
        return spend_scope == "provider_account" and spend_source == "provider_billing"
    return item_scope == spend_scope and item_source == spend_source


def _history_sample_day(timestamp: Any) -> str:
    raw = str(timestamp or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10] if len(raw) >= 10 else ""
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def _collapse_history_to_daily_latest(
    points: list[Dict[str, Any]],
    *,
    now: datetime,
) -> list[Dict[str, Any]]:
    daily: Dict[str, Dict[str, Any]] = {}
    for point in points:
        day = _history_sample_day(point.get("timestamp"))
        if not day:
            continue
        current = daily.get(day)
        if current is None or str(point.get("timestamp") or "") >= str(current.get("timestamp") or ""):
            daily[day] = point

    collapsed = [daily[key] for key in sorted(daily)]
    if not collapsed:
        return []

    month = now.strftime("%Y-%m")
    first_day = _history_sample_day(collapsed[0].get("timestamp"))
    if first_day > f"{month}-01" and _decimal_or_zero(collapsed[0].get("amount")) > 0:
        collapsed.insert(0, {
            "timestamp": f"{month}-01T00:00:00Z",
            "amount": 0.0,
            "display": "$0.00",
            "synthetic": True,
        })
    return collapsed


def _record_billing_sample(status: Dict[str, Any], *, forced_provider: Optional[str] = None) -> None:
    amount = _decimal_or_none(status.get("amount"))
    if amount is None:
        return

    now = datetime.now(timezone.utc)
    scope = _billing_scope(forced_provider)
    spend_source = _history_spend_source(status)
    spend_scope = _history_spend_scope(status)
    sample = {
        "timestamp": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "month": now.strftime("%Y-%m"),
        "scope": scope,
        "spend_source": spend_source,
        "spend_scope": spend_scope,
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
        and str(samples[-1].get("spend_source") or "").strip().lower() == spend_source
        and str(samples[-1].get("spend_scope") or "").strip().lower() == spend_scope
        and samples[-1].get("amount") == sample["amount"]
    ):
        samples[-1] = sample
    else:
        samples.append(sample)
    _write_billing_history(samples)


def _history_items_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
) -> list[Dict[str, Any]]:
    normalized_source = _normalized_history_spend_source(spend_source)
    normalized_scope = _normalized_history_spend_scope(spend_scope)
    items = []
    for item in _read_billing_history():
        if item.get("month") != month or item.get("scope") != scope:
            continue
        if not _history_item_matches_series(item, spend_source=normalized_source, spend_scope=normalized_scope):
            continue
        items.append(item)
    return sorted(items, key=lambda item: str(item.get("timestamp") or ""))


def _history_points_from_items(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
    points = []
    for item in items:
        amount = _decimal_or_none(item.get("amount"))
        if amount is None:
            continue
        points.append({
            "timestamp": item.get("timestamp") or "",
            "amount": _float_money(amount),
            "display": f"${_money(amount)}",
        })
    return points


def _history_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
) -> list[Dict[str, Any]]:
    current = _billing_month_datetime(month)
    points = _history_points_from_items(_history_items_for_month(
        month=month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
    ))
    return _collapse_history_to_daily_latest(points, now=current)


def _history_for_current_month(
    *,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
    now: Optional[datetime] = None,
) -> list[Dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    return _history_for_month(
        month=current.strftime("%Y-%m"),
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
    )


def _history_months_for_series(
    *,
    scope: str,
    spend_source: str,
    spend_scope: str,
) -> list[str]:
    months = set()
    normalized_source = _normalized_history_spend_source(spend_source)
    normalized_scope = _normalized_history_spend_scope(spend_scope)
    for item in _read_billing_history():
        month = str(item.get("month") or "").strip()
        if not _BILLING_MONTH_RE.fullmatch(month) or item.get("scope") != scope:
            continue
        if _history_item_matches_series(item, spend_source=normalized_source, spend_scope=normalized_scope):
            months.add(month)
    return sorted(months)


def _history_month_navigation(
    selected_month: str,
    available_months: list[str],
    *,
    current_month: str,
) -> tuple[str, str]:
    months = sorted({month for month in available_months if _BILLING_MONTH_RE.fullmatch(month)} | {selected_month})
    lower_bound = months[0] if months else selected_month
    previous = _shift_billing_month(selected_month, -1)
    next_month = _shift_billing_month(selected_month, 1)
    if previous < lower_bound and selected_month != current_month:
        previous = ""
    if next_month > current_month:
        next_month = ""
    return previous, next_month


def _history_month_status(
    *,
    month: str,
    forced_provider: Optional[str],
    spend_source: str,
    spend_scope: str,
) -> Dict[str, Any]:
    settings = _load_settings()
    warning_raw = str(settings.get("cloud_billing_monthly_warning_usd") or "").strip()
    warning = _decimal_or_zero(warning_raw) if warning_raw else None
    limit_raw = str(settings.get("cloud_billing_monthly_limit_usd") or "").strip()
    limit = _decimal_or_zero(limit_raw) if limit_raw else None
    scope = _billing_scope(forced_provider)
    items = _history_items_for_month(
        month=month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
    )
    latest = items[-1] if items else {}
    amount = _decimal_or_none(latest.get("amount")) if latest else Decimal("0")
    amount = amount or Decimal("0")
    accounts = latest.get("accounts") if isinstance(latest.get("accounts"), list) else []
    provider_amount = None
    if spend_scope == "model_usage" and accounts:
        provider_amount = sum((_decimal_or_zero(item.get("amount")) for item in accounts if isinstance(item, dict)), Decimal("0"))
    provider_label = latest.get("provider_label") or ("Model spend" if spend_scope == "model_usage" else "Cloud")
    source_label = _history_source_label(spend_source)

    return {
        "ok": bool(latest),
        "enabled": bool(settings.get("cloud_billing_enabled", False)),
        "configured": bool(latest),
        "status": "ok" if latest else "no_history",
        "error": "" if latest else f"No saved billing history for {_billing_month_label(month)}",
        "currency": latest.get("currency") or "USD",
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "warning_usd": _money(warning) if warning is not None else None,
        "limit_usd": _money(limit) if limit is not None else None,
        "over_warning": bool(warning is not None and amount >= warning),
        "over_limit": bool(limit is not None and amount >= limit),
        "limit_check_blocked": False,
        "refresh_seconds": _clamp_refresh_seconds(settings.get("cloud_billing_refresh_seconds")),
        "updated_at": latest.get("timestamp") or _utc_now_iso(),
        "cached": True,
        "provider": latest.get("provider") or ("local_usage" if spend_source == "usage_ledger" else "multiple"),
        "provider_label": provider_label,
        "provider_short_label": "AI" if spend_scope == "model_usage" else "ALL",
        "provider_token_hint": "Saved billing history",
        "provider_amount": _money(provider_amount) if provider_amount is not None and provider_amount > 0 else None,
        "provider_display": f"${_money(provider_amount)}" if provider_amount is not None and provider_amount > 0 else "",
        "spend_source": spend_source,
        "spend_scope": spend_scope,
        "source_label": source_label,
        "accounts": [dict(item) for item in accounts if isinstance(item, dict)],
        "history_only": True,
    }


def _chart_provider_model_accounts(status: Dict[str, Any], group_by: str) -> list[Dict[str, Any]]:
    accounts = []
    for item in status.get("accounts", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        provider_label = str(item.get("provider_label") or provider or "Provider").strip()
        source_label = str(item.get("model_spend_source_label") or item.get("model_spend_source") or "Provider model billing")
        if group_by == "model":
            for model in item.get("model_spend_models", []):
                if not isinstance(model, dict):
                    continue
                amount = _decimal_or_none(model.get("amount")) or Decimal("0")
                accounts.append({
                    "id": model.get("id") or model.get("label") or "model",
                    "label": model.get("label") or model.get("id") or "Model",
                    "provider": provider,
                    "provider_label": provider_label,
                    "amount": _float_money(amount) or 0.0,
                    "display": model.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": f"{_int_or_zero(model.get('events'))} billed line items" if model.get("events") else "",
                    "error": "",
                    "source_kind": "provider_model_billing",
                    "source_label": source_label,
                })
            continue

        amount = _decimal_or_none(item.get("model_amount"))
        if amount is None:
            continue
        accounts.append({
            "id": "model-" + str(item.get("account_id") or item.get("id") or provider or "provider"),
            "label": item.get("model_spend_label") or f"{provider_label} model billing",
            "provider": provider,
            "provider_label": provider_label,
            "amount": _float_money(amount) or 0.0,
            "display": item.get("model_display") or f"${_money(amount)}",
            "ok": True,
            "status": "",
            "error": "",
            "source_kind": "provider_model_billing",
            "source_label": source_label,
        })
    accounts.sort(key=lambda account: _decimal_or_zero(account.get("amount")), reverse=True)
    return accounts


def _chart_accounts(status: Dict[str, Any]) -> list[Dict[str, Any]]:
    accounts = []
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    group_by = str(status.get("group_by") or "provider").lower()
    if status.get("spend_source") == "provider_model_billing":
        provider_model_accounts = _chart_provider_model_accounts(status, group_by)
        if provider_model_accounts:
            return provider_model_accounts
    include_provider_accounts = status.get("spend_scope") != "model_usage"
    local_provider_usage: Dict[str, Dict[str, Any]] = {}
    if local_usage and local_usage.get("enabled"):
        for item in local_usage.get("providers", []):
            if not isinstance(item, dict):
                continue
            key = str(item.get("id") or item.get("label") or "").strip().lower()
            if key:
                local_provider_usage[key] = _usage_breakdown(item)
    if local_usage and local_usage.get("enabled"):
        if group_by == "model":
            for item in local_usage.get("models", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                usage = _usage_breakdown(item)
                accounts.append({
                    "id": item.get("id") or item.get("label") or "model",
                    "label": item.get("label") or item.get("id") or "Model",
                    "provider": "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": _usage_status(usage),
                    "error": "",
                    "usage": usage,
                    "source_kind": "usage_ledger",
                    "source_label": "Usage estimate",
                })
        elif group_by == "provider":
            for item in local_usage.get("providers", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                usage = _usage_breakdown(item)
                accounts.append({
                    "id": "usage-" + str(item.get("id") or item.get("label") or "provider"),
                    "label": str(item.get("label") or item.get("id") or "Provider") + " model usage",
                    "provider": item.get("id") or "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": _usage_status(usage),
                    "error": "",
                    "usage": usage,
                    "source_kind": "usage_ledger",
                    "source_label": "Usage estimate",
                })
        elif local_usage.get("events") or not status.get("accounts"):
            amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
            usage = _usage_breakdown(local_usage)
            accounts.append({
                "id": "local-model-usage",
                "label": "Tracked model usage",
                "provider": "local_usage",
                "provider_label": "Local usage",
                "amount": _float_money(amount) or 0.0,
                "display": local_usage.get("display") or f"${_money(amount)}",
                "ok": True,
                "status": _usage_status(usage),
                "error": "",
                "usage": usage,
                "source_kind": "usage_ledger",
                "source_label": "Usage estimate",
            })
    for item in status.get("accounts", []):
        if not include_provider_accounts:
            continue
        if not isinstance(item, dict):
            continue
        amount = _decimal_or_none(item.get("amount")) or Decimal("0")
        label = str(item.get("account_label") or item.get("label") or item.get("provider_label") or "Cloud").strip()
        provider_label = str(item.get("provider_label") or item.get("provider") or "").strip()
        provider_key = str(item.get("provider") or "").strip().lower()
        usage = (local_provider_usage.get(provider_key) or {}) if group_by != "provider" else {}
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
            "usage": usage,
            "source_kind": "provider_billing",
            "source_label": "Provider billing",
        })

    if not accounts and status.get("amount") is not None:
        amount = _decimal_or_none(status.get("amount")) or Decimal("0")
        source_kind = status.get("spend_source") or "provider_billing"
        source_label = status.get("source_label") or (
            "Provider billing" if source_kind == "provider_billing" else "Usage estimate"
        )
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
            "source_kind": source_kind,
            "source_label": source_label,
        })
    return accounts


def build_spending_graph_payload(
    status: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
    now: Optional[datetime] = None,
    month: str = "",
) -> Dict[str, Any]:
    current = now or datetime.now(timezone.utc)
    selected_month = _billing_month(month or status.get("month"), now=current)
    month_reference = _billing_month_datetime(selected_month)
    period = str(status.get("period") or "month")
    is_current_month = selected_month == current.strftime("%Y-%m")
    days_in_month = monthrange(month_reference.year, month_reference.month)[1]
    elapsed_days = max(1, current.day if is_current_month else days_in_month)
    amount = _decimal_or_none(status.get("amount"))
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    if amount is None and local_usage:
        amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
    amount = amount or Decimal("0")
    warning = _decimal_or_none(status.get("warning_usd"))
    limit = _decimal_or_none(status.get("limit_usd"))
    monthly_warning = warning if period == "month" else None
    monthly_limit = limit if period == "month" else None
    daily_warning = warning if period == "day" else None
    daily_limit = limit if period == "day" else None
    projected = (
        (amount / Decimal(elapsed_days)) * Decimal(days_in_month)
        if period == "month" and is_current_month and amount > 0
        else amount
    )
    scope = _billing_scope(forced_provider)
    spend_source = _history_spend_source(status)
    spend_scope = _history_spend_scope(status)
    history = _history_for_month(
        month=selected_month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
    )
    available_months = _history_months_for_series(scope=scope, spend_source=spend_source, spend_scope=spend_scope)
    if is_current_month and selected_month not in available_months:
        available_months = sorted([*available_months, selected_month])
    previous_month, next_month = _history_month_navigation(
        selected_month,
        available_months,
        current_month=current.strftime("%Y-%m"),
    )
    group_by = str(status.get("group_by") or "provider").lower()
    usage_payload = _chart_usage_payload(local_usage)
    title = "Model Spend" if status.get("spend_scope") == "model_usage" or status.get("provider") == "local_usage" else "Cloud Account Spend"
    if group_by == "model":
        title += " by Model"
    elif group_by == "provider":
        title += " by Provider"
    provider_amount = _decimal_or_none(status.get("provider_amount"))
    notice = status.get("error") or ""
    expose_provider_total = status.get("spend_scope") != "model_usage"

    return {
        "version": 1,
        "kind": "billing-spend",
        "title": title,
        "subtitle": (
            "Today"
            if period == "day"
            else f"{_billing_month_label(selected_month)} month-to-date" if is_current_month else _billing_month_label(selected_month)
        ),
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
        "monthly_warning": _float_money(monthly_warning),
        "monthly_warning_display": f"${_money(monthly_warning)}" if monthly_warning is not None else "",
        "monthly_limit": _float_money(monthly_limit),
        "monthly_limit_display": f"${_money(monthly_limit)}" if monthly_limit is not None else "",
        "daily_warning": _float_money(daily_warning),
        "daily_warning_display": f"${_money(daily_warning)}" if daily_warning is not None else "",
        "daily_limit": _float_money(daily_limit),
        "daily_limit_display": f"${_money(daily_limit)}" if daily_limit is not None else "",
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
        "spend_source": status.get("spend_source") or "provider_billing",
        "spend_scope": status.get("spend_scope") or "provider_account",
        "source_label": status.get("source_label") or "",
        "provider_total": _float_money(provider_amount) if expose_provider_total else None,
        "provider_total_display": f"${_money(provider_amount)}" if expose_provider_total and provider_amount is not None else "",
        "period": period,
        "month": selected_month,
        "month_label": _billing_month_label(selected_month),
        "is_current_month": is_current_month,
        "available_months": available_months,
        "previous_month": previous_month,
        "next_month": next_month,
        "scope": scope,
        "provider_query": _normalized_provider(forced_provider) if forced_provider else "",
        "history_only": bool(status.get("history_only", False)),
        "group_by": group_by,
        "local_usage": local_usage or {},
        "usage": usage_payload,
        "source_note": _chart_source_note(status, usage_payload),
        "accounts": _chart_accounts(status),
        "history": history,
        "notice": notice,
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
        "spend_source": "usage_ledger",
        "spend_scope": "model_usage",
        "source_label": "Usage ledger",
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
    model_amount = normalized.pop("model_amount_decimal", None)
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
    if model_amount is not None:
        payload.update({
            "model_amount": _money(model_amount),
            "model_display": f"${_money(model_amount)}",
            "model_spend_scope": "model_usage",
            "model_spend_source_kind": "provider_model_billing",
            "model_spend_source_label": normalized.get("model_spend_source") or "Provider model billing",
        })
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
        return _apply_primary_spend_source(
            payload,
            settings=settings,
            warning=warning,
            limit=limit,
            forced_provider=forced_provider,
        )

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

    provider_payload = {
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
    payload = dict(provider_payload)
    payload["accounts"] = [dict(item) for item in account_results]
    _attach_local_usage(payload)
    payload = _apply_primary_spend_source(
        payload,
        settings=settings,
        warning=warning,
        limit=limit,
        forced_provider=forced_provider,
    )
    _CACHE.update({
        "fingerprint": fingerprint,
        "expires_at": now + refresh_seconds,
        "payload": provider_payload,
    })
    return payload


def get_spending_graph_status(
    *,
    refresh: bool = False,
    forced_provider: Optional[str] = None,
    period: str = "month",
    group_by: str = "provider",
    month: str = "",
    spend_source: str = "",
    spend_scope: str = "",
) -> Dict[str, Any]:
    current = datetime.now(timezone.utc)
    normalized_period = "day" if str(period or "").lower() in {"day", "today"} else "month"
    normalized_group = str(group_by or "provider").strip().lower()
    if normalized_group not in {"provider", "model", "summary"}:
        normalized_group = "provider"
    selected_month = _billing_month(month, now=current)
    is_current_month = selected_month == current.strftime("%Y-%m")

    if normalized_period == "day":
        settings = _load_settings()
        status = _local_only_payload(
            period="day",
            warning_usd=str(settings.get("cloud_billing_daily_warning_usd") or "").strip() or None,
            limit_usd=str(settings.get("cloud_billing_daily_limit_usd") or "").strip() or None,
            refresh_seconds=_clamp_refresh_seconds(settings.get("cloud_billing_refresh_seconds")),
        )
    elif not is_current_month:
        status = _history_month_status(
            month=selected_month,
            forced_provider=forced_provider,
            spend_source=_normalized_history_spend_source(spend_source),
            spend_scope=_normalized_history_spend_scope(spend_scope),
        )
    else:
        status = get_monthly_spend_status(refresh=refresh, forced_provider=forced_provider)
    status["period"] = normalized_period
    status["group_by"] = normalized_group
    if (
        normalized_period == "month"
        and is_current_month
        and status.get("spend_source") != "usage_ledger"
        and status.get("amount") is not None
    ):
        _record_billing_sample(status, forced_provider=forced_provider)
    chart = build_spending_graph_payload(
        status,
        forced_provider=forced_provider,
        now=current,
        month=selected_month,
    )
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
        month: str = "",
        spend_source: str = "",
        spend_scope: str = "",
    ) -> Dict[str, Any]:
        require_admin(request)
        forced_provider = provider.strip() if provider else None
        return get_spending_graph_status(
            refresh=refresh,
            forced_provider=forced_provider,
            period=period,
            group_by=group_by,
            month=month,
            spend_source=spend_source,
            spend_scope=spend_scope,
        )

    @router.get("/usage-summary")
    def usage_summary(request: Request, period: str = "month") -> Dict[str, Any]:
        require_admin(request)
        return _local_usage_payload(period)

    @router.get("/{provider}/monthly-spend")
    def provider_monthly_spend(provider: str, request: Request, refresh: bool = False) -> Dict[str, Any]:
        return _monthly_spend(request, refresh=refresh, forced_provider=provider)

    return router
