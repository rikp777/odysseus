"""Local model usage ledger and budget helpers.

Provider billing APIs are useful for reconciliation, but they lag and are
provider-specific. This module records Odysseus' own model-call usage in a
normalized local ledger so spend graphs and budget checks can work across any
provider that exposes token usage.
"""

from __future__ import annotations

from calendar import monthrange
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional
import uuid

from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
    display_money as _display_money,
    float_money as _float_money,
    stored_money as _stored_money,
)
from src.provider_identity import is_remote_billable_endpoint, provider_from_endpoint
from src.settings import load_settings


def _usage_display_money(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    magnitude = abs(value)
    precision = Decimal("0.0001") if magnitude and magnitude < Decimal("0.01") else Decimal("0.01")
    return f"${value.quantize(precision, rounding=ROUND_HALF_UP)}"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _period_range(period: str, now: Optional[datetime] = None) -> tuple[datetime, datetime, str]:
    current = now or _utc_now()
    current = current.replace(tzinfo=None)
    kind = (period or "month").strip().lower()
    if kind in {"day", "today"}:
        start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + timedelta(days=1)
        return start, end, "day"
    start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    days = monthrange(current.year, current.month)[1]
    end = start + timedelta(days=days)
    return start, end, "month"


def _pricing_for(endpoint_url: str, model: str) -> Optional[Dict[str, Any]]:
    try:
        from src.model_pricing import _model_pricing_for_endpoint
        return _model_pricing_for_endpoint(endpoint_url, model)
    except Exception:
        return None


def estimate_usage_cost(
    endpoint_url: str,
    model: str,
    input_tokens: int,
    output_tokens: int,
) -> Dict[str, Any]:
    """Return normalized cost metadata for a model usage event."""
    pricing = _pricing_for(endpoint_url, model) or {}
    provider = pricing.get("provider") or provider_from_endpoint(endpoint_url)
    unit = str(pricing.get("unit") or "1M tokens").lower()
    denominator = Decimal("1000000") if "1m" in unit or "million" in unit else Decimal("1")

    input_cost = None
    output_cost = None
    total_cost = None
    if pricing.get("input_usd_per_unit") is not None or pricing.get("output_usd_per_unit") is not None:
        input_rate = _decimal_or_zero(pricing.get("input_usd_per_unit"))
        output_rate = _decimal_or_zero(pricing.get("output_usd_per_unit"))
        input_cost = (Decimal(max(input_tokens, 0)) / denominator) * input_rate
        output_cost = (Decimal(max(output_tokens, 0)) / denominator) * output_rate
        total_cost = input_cost + output_cost
    elif pricing.get("price_usd_per_unit") is not None:
        rate = _decimal_or_zero(pricing.get("price_usd_per_unit"))
        total_cost = (Decimal(max(input_tokens + output_tokens, 0)) / denominator) * rate

    return {
        "provider": provider,
        "pricing": pricing or None,
        "currency": pricing.get("currency") or "USD",
        "input_cost_usd": _stored_money(input_cost),
        "output_cost_usd": _stored_money(output_cost),
        "total_cost_usd": _stored_money(total_cost),
        "known_cost": total_cost is not None,
    }


def record_model_usage(
    *,
    owner: Optional[str],
    session_id: Optional[str],
    message_id: Optional[str],
    endpoint_url: str,
    model: str,
    input_tokens: Any = 0,
    output_tokens: Any = 0,
    source: str = "estimated",
) -> Optional[str]:
    settings = load_settings()
    if settings.get("cloud_billing_usage_ledger_enabled") is False:
        return None
    try:
        in_tokens = max(int(input_tokens or 0), 0)
    except (TypeError, ValueError):
        in_tokens = 0
    try:
        out_tokens = max(int(output_tokens or 0), 0)
    except (TypeError, ValueError):
        out_tokens = 0
    if not model or (in_tokens == 0 and out_tokens == 0):
        return None

    cost = estimate_usage_cost(endpoint_url, model, in_tokens, out_tokens)
    event_id = uuid.uuid4().hex
    from core.database import ModelUsageEvent, SessionLocal

    db = SessionLocal()
    try:
        row = ModelUsageEvent(
            id=event_id,
            owner=owner or None,
            session_id=session_id or None,
            message_id=message_id or None,
            provider=cost["provider"],
            endpoint_url=endpoint_url or "",
            model=model,
            input_tokens=in_tokens,
            output_tokens=out_tokens,
            total_tokens=in_tokens + out_tokens,
            input_cost_usd=cost.get("input_cost_usd"),
            output_cost_usd=cost.get("output_cost_usd"),
            total_cost_usd=cost.get("total_cost_usd"),
            currency=cost.get("currency") or "USD",
            source=source or "estimated",
            created_at=_utc_now(),
        )
        db.add(row)
        db.commit()
        return event_id
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def record_model_usage_from_metrics(
    *,
    owner: Optional[str],
    session_id: Optional[str],
    message_id: Optional[str],
    endpoint_url: str,
    model: str,
    metrics: Optional[Dict[str, Any]],
) -> Optional[str]:
    if not metrics:
        return None
    source = str(metrics.get("usage_source") or "unknown")
    return record_model_usage(
        owner=owner,
        session_id=session_id,
        message_id=message_id,
        endpoint_url=endpoint_url,
        model=str(metrics.get("model") or model or ""),
        input_tokens=metrics.get("input_tokens", 0),
        output_tokens=metrics.get("output_tokens", 0),
        source=source,
    )


def _usage_summary_from_rows(
    rows: list[Any],
    *,
    period: str,
    start: Optional[datetime] = None,
    end: Optional[datetime] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    total_cost = Decimal("0")
    known_cost_events = 0
    input_tokens = 0
    output_tokens = 0
    provider_map: Dict[str, Dict[str, Any]] = {}
    model_map: Dict[str, Dict[str, Any]] = {}

    for row in rows:
        input_tokens += int(row.input_tokens or 0)
        output_tokens += int(row.output_tokens or 0)
        cost = _decimal_or_none(row.total_cost_usd)
        if cost is not None:
            total_cost += cost
            known_cost_events += 1
        provider = row.provider or "unknown"
        model = row.model or "unknown"
        for bucket, key in ((provider_map, provider), (model_map, model)):
            item = bucket.setdefault(key, {
                "id": key,
                "label": key,
                "events": 0,
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "amount": Decimal("0"),
                "known_cost_events": 0,
            })
            item["events"] += 1
            item["input_tokens"] += int(row.input_tokens or 0)
            item["output_tokens"] += int(row.output_tokens or 0)
            item["total_tokens"] += int(row.total_tokens or 0)
            if cost is not None:
                item["amount"] += cost
                item["known_cost_events"] += 1

    def _bucket_values(bucket: Dict[str, Dict[str, Any]]) -> list[Dict[str, Any]]:
        values = []
        for item in bucket.values():
            amount = item["amount"]
            values.append({
                **{key: value for key, value in item.items() if key != "amount"},
                "amount": _float_money(amount) or 0.0,
                "display": _usage_display_money(amount),
            })
        values.sort(key=lambda item: item["amount"], reverse=True)
        return values

    normalized_period = (period or "month").strip().lower() or "month"
    current = now or _utc_now()
    if normalized_period == "month":
        elapsed_days = max(1, current.day)
        days_in_month = monthrange(current.year, current.month)[1]
        projected = (total_cost / Decimal(elapsed_days)) * Decimal(days_in_month) if total_cost > 0 else total_cost
    else:
        projected = total_cost

    result = {
        "enabled": load_settings().get("cloud_billing_usage_ledger_enabled") is not False,
        "period": normalized_period,
        "currency": "USD",
        "amount_decimal": total_cost,
        "amount": _stored_money(total_cost) or "0.000000",
        "amount_float": _float_money(total_cost) or 0.0,
        "display": _usage_display_money(total_cost),
        "projected_decimal": projected,
        "projected": _stored_money(projected) or "0.000000",
        "projected_display": _usage_display_money(projected),
        "events": len(rows),
        "known_cost_events": known_cost_events,
        "unknown_cost_events": max(len(rows) - known_cost_events, 0),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "providers": _bucket_values(provider_map),
        "models": _bucket_values(model_map),
    }
    if start is not None:
        result["start"] = start.isoformat() + "Z"
    if end is not None:
        result["end"] = end.isoformat() + "Z"
    return result


def _message_usage_summaries(rows: list[Any]) -> list[Dict[str, Any]]:
    grouped: "OrderedDict[str, list[Any]]" = OrderedDict()
    for row in rows:
        message_id = str(row.message_id or "").strip()
        if not message_id:
            continue
        grouped.setdefault(message_id, []).append(row)

    messages = []
    for message_id, group_rows in grouped.items():
        summary = _usage_summary_from_rows(group_rows, period="message")
        summary.pop("amount_decimal", None)
        summary.pop("projected_decimal", None)
        first = group_rows[0]
        last = group_rows[-1]
        providers = sorted({str(row.provider or "unknown") for row in group_rows})
        models = sorted({str(row.model or "unknown") for row in group_rows})
        messages.append({
            "message_id": message_id,
            "provider": providers[0] if len(providers) == 1 else "multiple",
            "model": models[0] if len(models) == 1 else "multiple",
            "created_at": getattr(first, "created_at", None).isoformat() + "Z" if getattr(first, "created_at", None) else "",
            "updated_at": getattr(last, "created_at", None).isoformat() + "Z" if getattr(last, "created_at", None) else "",
            **summary,
        })
    return messages


def get_usage_summary(
    *,
    period: str = "month",
    owner: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    start, end, normalized_period = _period_range(period, now=now)
    from core.database import ModelUsageEvent, SessionLocal

    db = SessionLocal()
    try:
        q = db.query(ModelUsageEvent).filter(
            ModelUsageEvent.created_at >= start,
            ModelUsageEvent.created_at < end,
        )
        if owner:
            q = q.filter(ModelUsageEvent.owner == owner)
        rows = q.order_by(ModelUsageEvent.created_at.asc()).all()
    finally:
        db.close()

    return _usage_summary_from_rows(rows, period=normalized_period, start=start, end=end, now=now)


def get_session_usage_summary(
    *,
    session_id: str,
    owner: Optional[str] = None,
) -> Dict[str, Any]:
    from core.database import ModelUsageEvent, SessionLocal

    db = SessionLocal()
    try:
        q = db.query(ModelUsageEvent).filter(ModelUsageEvent.session_id == session_id)
        if owner:
            q = q.filter(ModelUsageEvent.owner == owner)
        rows = q.order_by(ModelUsageEvent.created_at.asc()).all()
    finally:
        db.close()

    summary = _usage_summary_from_rows(rows, period="session")
    summary["session_id"] = session_id
    summary["messages"] = _message_usage_summaries(rows)
    return summary


def local_budget_block_reason(endpoint_url: str, model: str = "", owner: Optional[str] = None) -> Optional[str]:
    """Return a block reason if local usage-ledger budgets are exceeded."""
    if not is_remote_billable_endpoint(endpoint_url):
        return None
    settings = load_settings()
    if not settings.get("cloud_billing_enabled"):
        return None
    if settings.get("cloud_billing_budget_enforcement_enabled") is False:
        return None
    if settings.get("cloud_billing_usage_ledger_enabled") is False:
        return None

    checks = [
        ("day", settings.get("cloud_billing_daily_limit_usd")),
        ("month", settings.get("cloud_billing_monthly_limit_usd")),
    ]
    for period, raw_limit in checks:
        limit = _decimal_or_none(raw_limit)
        if limit is None or limit <= 0:
            continue
        summary = get_usage_summary(period=period, owner=owner)
        amount = summary["amount_decimal"]
        if amount >= limit:
            label = "daily" if period == "day" else "monthly"
            return (
                f"Cloud model budget reached: local {label} model spend is "
                f"{_display_money(amount)}, limit is {_display_money(limit)}. "
                "Remote model calls are blocked until the limit is raised or the period resets."
            )
    return None
