"""Public billing safety events and budget-state helpers."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from core.atomic_io import atomic_write_json
from src.billing.common import decimal_or_none, display_money, money, utc_now_iso


DEFAULT_BILLING_EVENTS_FILE = Path("data/billing_events.json")
MAX_BILLING_EVENTS = 200
MAX_PUBLIC_EVENTS = 12
_SEVERITIES = {"info", "warning", "danger"}
_SECRET_KEY_PARTS = ("token", "secret", "password", "api_key", "key")


def read_billing_events(event_file: Path = DEFAULT_BILLING_EVENTS_FILE) -> list[Dict[str, Any]]:
    try:
        with open(event_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def write_billing_events(
    events: list[Dict[str, Any]],
    *,
    event_file: Path = DEFAULT_BILLING_EVENTS_FILE,
    max_events: int = MAX_BILLING_EVENTS,
) -> None:
    atomic_write_json(str(event_file), events[-max_events:], indent=2)


def _event_timestamp(now: Optional[datetime] = None) -> str:
    current = now or datetime.now(timezone.utc)
    return current.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _public_value(item)
            for key, item in value.items()
            if not any(part in str(key).lower() for part in _SECRET_KEY_PARTS)
        }
    if isinstance(value, list):
        return [_public_value(item) for item in value[:20]]
    if isinstance(value, tuple):
        return [_public_value(item) for item in value[:20]]
    if isinstance(value, Decimal):
        return money(value)
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _event_key(kind: str, source: str, details: Dict[str, Any]) -> str:
    raw = json.dumps(
        {
            "kind": kind,
            "source": source,
            "period": details.get("period"),
            "scope": details.get("spend_scope"),
            "provider": details.get("provider"),
            "model": details.get("model"),
            "limit": details.get("limit"),
            "amount": details.get("amount"),
            "status": details.get("status"),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def record_billing_event(
    *,
    kind: str,
    severity: str,
    title: str,
    message: str = "",
    source: str = "",
    details: Optional[Dict[str, Any]] = None,
    dedupe_key: str = "",
    event_file: Path = DEFAULT_BILLING_EVENTS_FILE,
    max_events: int = MAX_BILLING_EVENTS,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Record or update a public billing event without storing secrets."""

    safe_details = _public_value(details or {})
    if not isinstance(safe_details, dict):
        safe_details = {}
    normalized_kind = str(kind or "billing_event").strip().lower() or "billing_event"
    normalized_source = str(source or safe_details.get("source") or "").strip().lower()
    normalized_severity = str(severity or "info").strip().lower()
    if normalized_severity not in _SEVERITIES:
        normalized_severity = "info"
    key = dedupe_key or _event_key(normalized_kind, normalized_source, safe_details)
    timestamp = _event_timestamp(now)
    events = read_billing_events(event_file)

    if events and events[-1].get("dedupe_key") == key:
        event = dict(events[-1])
        event.update({
            "last_seen_at": timestamp,
            "count": int(event.get("count") or 1) + 1,
            "severity": normalized_severity,
            "title": str(title or "").strip(),
            "message": str(message or "").strip(),
            "details": safe_details,
        })
        events[-1] = event
    else:
        event = {
            "id": hashlib.sha256(f"{timestamp}\n{key}\n{len(events)}".encode("utf-8")).hexdigest()[:16],
            "kind": normalized_kind,
            "severity": normalized_severity,
            "title": str(title or "").strip(),
            "message": str(message or "").strip(),
            "source": normalized_source,
            "details": safe_details,
            "dedupe_key": key,
            "created_at": timestamp,
            "last_seen_at": timestamp,
            "count": 1,
        }
        events.append(event)

    write_billing_events(events, event_file=event_file, max_events=max_events)
    return public_billing_event(event)


def public_billing_event(event: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "id": event.get("id") or "",
        "kind": event.get("kind") or "",
        "severity": event.get("severity") or "info",
        "title": event.get("title") or "",
        "message": event.get("message") or "",
        "source": event.get("source") or "",
        "details": _public_value(event.get("details") if isinstance(event.get("details"), dict) else {}),
        "created_at": event.get("created_at") or "",
        "last_seen_at": event.get("last_seen_at") or event.get("created_at") or "",
        "count": int(event.get("count") or 1),
    }


def recent_billing_events(
    *,
    limit: int = MAX_PUBLIC_EVENTS,
    event_file: Path = DEFAULT_BILLING_EVENTS_FILE,
) -> list[Dict[str, Any]]:
    count = max(1, min(int(limit or MAX_PUBLIC_EVENTS), 50))
    events = read_billing_events(event_file)
    return [public_billing_event(item) for item in reversed(events[-count:])]


def _status_period(status: Dict[str, Any]) -> str:
    return "day" if str(status.get("period") or "").strip().lower() == "day" else "month"


def budget_state_from_status(
    status: Dict[str, Any],
    *,
    enforcement_enabled: bool = True,
) -> Dict[str, Any]:
    period = _status_period(status)
    amount = decimal_or_none(status.get("amount"))
    limit = decimal_or_none(status.get("limit_usd"))
    warning = decimal_or_none(status.get("warning_usd"))
    source = str(status.get("spend_source") or "").strip() or "provider_billing"
    scope = str(status.get("spend_scope") or status.get("amount_scope") or "").strip() or "provider_account"
    over_limit = bool(status.get("over_limit"))
    over_warning = bool(status.get("over_warning"))
    limit_check_blocked = bool(status.get("limit_check_blocked"))
    block_remote = bool(enforcement_enabled and (limit_check_blocked or (scope == "model_usage" and over_limit)))

    if limit_check_blocked and enforcement_enabled:
        code = "billing_unverified"
        reason = (
            f"Cloud spend limit is set to {display_money(limit)}, but Odysseus could not verify current "
            "provider spend. Cloud model calls are blocked to avoid accidental overspend."
        )
    elif limit_check_blocked:
        code = "billing_unverified"
        reason = "Provider spend could not be verified, but budget enforcement is turned off."
    elif block_remote:
        code = f"{period}_limit_reached"
        reason = (
            f"Cloud spend limit reached: current {period}-to-date model spend is "
            f"{status.get('display') or display_money(amount)}, limit is {display_money(limit)}. "
            "Cloud model calls are blocked until the limit is raised or the billing period resets."
        )
    elif over_warning and scope == "model_usage":
        code = f"{period}_warning_reached"
        reason = (
            f"Cloud spend warning reached: current {period}-to-date model spend is "
            f"{status.get('display') or display_money(amount)}, warning is {display_money(warning)}."
        )
    else:
        code = "ok"
        reason = ""

    return {
        "enabled": bool(status.get("enabled")),
        "configured": bool(status.get("configured")),
        "enforcement_enabled": bool(enforcement_enabled),
        "period": period,
        "source": source,
        "source_label": status.get("source_label") or "",
        "spend_scope": scope,
        "amount": money(amount or Decimal("0")) if amount is not None else "",
        "display": status.get("display") or display_money(amount),
        "warning": money(warning) if warning is not None else "",
        "warning_display": display_money(warning),
        "limit": money(limit) if limit is not None else "",
        "limit_display": display_money(limit),
        "over_warning": over_warning,
        "over_limit": over_limit,
        "limit_check_blocked": limit_check_blocked,
        "block_remote_models": block_remote,
        "block_code": code,
        "block_reason": reason,
        "updated_at": status.get("updated_at") or utc_now_iso(),
    }


def sync_billing_events_from_status(
    status: Dict[str, Any],
    *,
    enforcement_enabled: bool = True,
    event_file: Path = DEFAULT_BILLING_EVENTS_FILE,
    now: Optional[datetime] = None,
) -> list[Dict[str, Any]]:
    """Record threshold/provider events derived from a billing status payload."""

    state = budget_state_from_status(status, enforcement_enabled=enforcement_enabled)
    source = str(state.get("source") or "")
    scope = str(state.get("spend_scope") or "")
    period = str(state.get("period") or "month")

    if state.get("limit_check_blocked") and state.get("enforcement_enabled"):
        record_billing_event(
            kind="billing_unverified",
            severity="danger",
            title="Budget check blocked",
            message=state.get("block_reason") or "Provider spend could not be verified while a limit is configured.",
            source=source,
            details={**state, "status": status.get("status") or ""},
            event_file=event_file,
            now=now,
        )
    elif state.get("limit_check_blocked"):
        record_billing_event(
            kind="billing_unverified",
            severity="warning",
            title="Billing check unavailable",
            message=state.get("block_reason") or "Provider spend could not be verified.",
            source=source,
            details={**state, "status": status.get("status") or ""},
            event_file=event_file,
            now=now,
        )
    elif state.get("block_remote_models"):
        record_billing_event(
            kind="budget_limit_reached",
            severity="danger",
            title=f"{period.title()} max usage reached",
            message=state.get("block_reason") or "Remote model calls are blocked by the configured budget.",
            source=source,
            details=state,
            event_file=event_file,
            now=now,
        )
    elif state.get("over_warning") and scope == "model_usage":
        record_billing_event(
            kind="budget_warning_reached",
            severity="warning",
            title=f"{period.title()} warning reached",
            message=state.get("block_reason") or "Model spend reached the configured warning threshold.",
            source=source,
            details=state,
            event_file=event_file,
            now=now,
        )

    for row in status.get("provider_health", []):
        if not isinstance(row, dict):
            continue
        if not row.get("configured") or row.get("ok"):
            continue
        provider_label = row.get("provider_label") or row.get("account_label") or "Provider"
        message = row.get("last_error") or row.get("status_label") or "Billing check failed"
        record_billing_event(
            kind="provider_billing_check_failed",
            severity="warning",
            title=f"{provider_label} billing check failed",
            message=message,
            source=str(row.get("provider") or source),
            details={
                "provider": row.get("provider") or "",
                "provider_label": provider_label,
                "account_id": row.get("account_id") or "",
                "status": row.get("status") or "",
                "status_label": row.get("status_label") or "",
            },
            event_file=event_file,
            now=now,
        )

    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else {}
    unknown_cost_events = int(local_usage.get("unknown_cost_events") or 0)
    if unknown_cost_events > 0:
        record_billing_event(
            kind="model_cost_unknown",
            severity="warning",
            title="Some model usage is unpriced",
            message=f"{unknown_cost_events} usage event(s) could not be priced from the model catalog.",
            source="usage_ledger",
            details={
                "events": local_usage.get("events") or 0,
                "unknown_cost_events": unknown_cost_events,
                "known_cost_events": local_usage.get("known_cost_events") or 0,
            },
            event_file=event_file,
            now=now,
        )

    return recent_billing_events(event_file=event_file)
