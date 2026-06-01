"""Local model usage ledger and budget helpers.

Provider billing APIs are useful for reconciliation, but they lag and are
provider-specific. This module records Odysseus' own model-call usage in a
normalized local ledger so spend graphs and budget checks can work across any
provider that exposes token usage.
"""

from __future__ import annotations

from calendar import monthrange
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import ipaddress
from typing import Any, Dict, Optional
from urllib.parse import urlparse
import uuid

from src.settings import load_settings


def _utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def _decimal_or_none(value: Any) -> Optional[Decimal]:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def _decimal_or_zero(value: Any) -> Decimal:
    return _decimal_or_none(value) or Decimal("0")


def _stored_money(value: Optional[Decimal]) -> Optional[str]:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


def _display_money(value: Optional[Decimal]) -> str:
    if value is None:
        return ""
    return f"${value.quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)}"


def _float_money(value: Optional[Decimal]) -> Optional[float]:
    if value is None:
        return None
    return float(value.quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP))


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


def _provider_for_endpoint(endpoint_url: str) -> str:
    value = (endpoint_url or "").lower()
    host = (urlparse(value).hostname or "").lower()
    if "inference.do-ai.run" in value or "inference.do-ai.run" in host:
        return "digitalocean"
    if "api.openai.com" in host:
        return "openai"
    if "anthropic.com" in host:
        return "anthropic"
    if "openrouter.ai" in host:
        return "openrouter"
    if "api.groq.com" in host:
        return "groq"
    if "api.mistral.ai" in host:
        return "mistral"
    if "api.together.xyz" in host or "api.together.ai" in host:
        return "together"
    if "fireworks.ai" in host:
        return "fireworks"
    if "generativelanguage.googleapis.com" in host:
        return "google"
    if "api.x.ai" in host:
        return "xai"
    if host:
        return host
    return "unknown"


def _is_remote_billable_url(endpoint_url: str) -> bool:
    try:
        host = (urlparse(endpoint_url or "").hostname or "").lower()
    except Exception:
        return False
    if not host:
        return False
    if host in {"localhost", "127.0.0.1", "0.0.0.0", "::1"} or host.endswith(".local"):
        return False
    try:
        ip = ipaddress.ip_address(host)
        tailscale = ipaddress.ip_network("100.64.0.0/10")
        if ip.is_loopback or ip.is_private or ip.is_link_local or ip in tailscale:
            return False
    except ValueError:
        pass
    return True


def _pricing_for(endpoint_url: str, model: str) -> Optional[Dict[str, Any]]:
    try:
        from routes.model_routes import _model_pricing_for_endpoint
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
    provider = pricing.get("provider") or _provider_for_endpoint(endpoint_url)
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
            amount = item.pop("amount")
            values.append({
                **item,
                "amount": _float_money(amount) or 0.0,
                "display": _display_money(amount),
            })
        values.sort(key=lambda item: item["amount"], reverse=True)
        return values

    current = now or _utc_now()
    elapsed_days = max(1, current.day if normalized_period == "month" else 1)
    days_in_month = monthrange(current.year, current.month)[1]
    projected = (total_cost / Decimal(elapsed_days)) * Decimal(days_in_month) if normalized_period == "month" and total_cost > 0 else total_cost

    return {
        "enabled": load_settings().get("cloud_billing_usage_ledger_enabled") is not False,
        "period": normalized_period,
        "start": start.isoformat() + "Z",
        "end": end.isoformat() + "Z",
        "currency": "USD",
        "amount_decimal": total_cost,
        "amount": _stored_money(total_cost) or "0.000000",
        "amount_float": _float_money(total_cost) or 0.0,
        "display": _display_money(total_cost),
        "projected_decimal": projected,
        "projected": _stored_money(projected) or "0.000000",
        "projected_display": _display_money(projected),
        "events": len(rows),
        "known_cost_events": known_cost_events,
        "unknown_cost_events": max(len(rows) - known_cost_events, 0),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": input_tokens + output_tokens,
        "providers": _bucket_values(provider_map),
        "models": _bucket_values(model_map),
    }


def local_budget_block_reason(endpoint_url: str, model: str = "", owner: Optional[str] = None) -> Optional[str]:
    """Return a block reason if local usage-ledger budgets are exceeded."""
    if not _is_remote_billable_url(endpoint_url):
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
        summary = get_usage_summary(period=period, owner=None)
        amount = summary["amount_decimal"]
        if amount >= limit:
            label = "daily" if period == "day" else "monthly"
            return (
                f"Cloud model budget reached: local {label} model spend is "
                f"{_display_money(amount)}, limit is {_display_money(limit)}. "
                "Remote model calls are blocked until the limit is raised or the period resets."
            )
    return None
