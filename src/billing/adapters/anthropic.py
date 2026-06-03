"""Anthropic billing adapter."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

from src.billing.adapters.common import (
    _billing_month_bounds,
    _estimate_provider_model_cost,
    _iter_usage_results,
    _model_billing_amount,
    _paged_get_json,
)
from src.billing.common import (
    decimal_or_zero as _decimal_or_zero,
    int_or_zero as _int_or_zero,
    money as _money,
    stored_money as _stored_money,
    utc_now_iso as _utc_now_iso,
)


_ANTHROPIC_MESSAGES_USAGE_URL = "https://api.anthropic.com/v1/organizations/usage_report/messages"


def _anthropic_messages_summary(pages: Any) -> Dict[str, Any]:
    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    models: Dict[str, Dict[str, Any]] = {}

    for result in _iter_usage_results(pages):
        model_label = str(result.get("model") or "Claude model").strip()
        cache_creation = result.get("cache_creation") if isinstance(result.get("cache_creation"), dict) else {}
        input_tokens = _int_or_zero(result.get("uncached_input_tokens"))
        cache_write_5m = _int_or_zero(cache_creation.get("ephemeral_5m_input_tokens"))
        cache_write_1h = _int_or_zero(cache_creation.get("ephemeral_1h_input_tokens"))
        cache_read = _int_or_zero(result.get("cache_read_input_tokens"))
        output_tokens = _int_or_zero(result.get("output_tokens"))
        requests = _int_or_zero(result.get("num_model_requests")) or 1
        cost = _estimate_provider_model_cost(
            "anthropic",
            model_label,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_write_5m_tokens=cache_write_5m,
            cache_write_1h_tokens=cache_write_1h,
            cache_read_tokens=cache_read,
        )
        if cost is None:
            continue
        total += cost
        total_tokens = input_tokens + cache_write_5m + cache_write_1h + cache_read + output_tokens
        item = {
            "id": model_label.lower(),
            "label": model_label,
            "model": model_label,
            "amount": _stored_money(cost) or "0.000000",
            "display": f"${_money(cost)}",
            "input_tokens": input_tokens,
            "cache_write_tokens": cache_write_5m + cache_write_1h,
            "cache_read_tokens": cache_read,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "events": requests,
        }
        items.append(item)
        model_key = model_label.lower()
        model = models.setdefault(model_key, {
            "id": model_key,
            "label": model_label,
            "amount_decimal": Decimal("0"),
            "events": 0,
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
        })
        model["amount_decimal"] += cost
        model["events"] += requests
        model["input_tokens"] += input_tokens + cache_write_5m + cache_write_1h + cache_read
        model["output_tokens"] += output_tokens
        model["total_tokens"] += total_tokens

    model_rows = []
    for model in models.values():
        amount = model.pop("amount_decimal")
        model_rows.append({
            **model,
            "amount": _stored_money(amount) or "0.000000",
            "display": f"${_money(amount)}",
        })
    model_rows.sort(key=lambda item: _decimal_or_zero(item["amount"]), reverse=True)

    return {
        "amount_decimal": total,
        "amount": _stored_money(total) or "0.000000",
        "display": f"${_money(total)}",
        "provider": "anthropic",
        "provider_label": "Anthropic",
        "label": "Anthropic Messages API model usage",
        "source_kind": "provider_model_billing",
        "source_label": "Anthropic usage estimate",
        "items": items,
        "models": model_rows,
    }


def _fetch_anthropic_billing(token: str) -> Dict[str, Any]:
    start, end = _billing_month_bounds()
    headers = {
        "x-api-key": token,
        "anthropic-version": "2023-06-01",
        "Content-Type": "application/json",
    }
    pages = _paged_get_json(
        _ANTHROPIC_MESSAGES_USAGE_URL,
        headers=headers,
        params=[
            ("starting_at", start.isoformat().replace("+00:00", "Z")),
            ("ending_at", end.isoformat().replace("+00:00", "Z")),
            ("bucket_width", "1d"),
            ("limit", "31"),
            ("group_by[]", "model"),
        ],
    )
    return {"messages_usage": pages}


def _anthropic_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    usage_summary = _anthropic_messages_summary(raw.get("messages_usage"))
    amount = _model_billing_amount(usage_summary) or Decimal("0")
    return {
        "amount_decimal": amount,
        "amount_scope": "model_usage",
        "month_to_date_usage": _money(amount),
        "generated_at": _utc_now_iso(),
        "model_amount_decimal": amount,
        "model_display": f"${_money(amount)}",
        "model_spend_label": str(usage_summary.get("label") or "Anthropic Messages API model usage"),
        "model_spend_source": str(usage_summary.get("source_label") or "Anthropic usage estimate"),
        "model_spend_items": usage_summary.get("items") if isinstance(usage_summary.get("items"), list) else [],
        "model_spend_models": usage_summary.get("models") if isinstance(usage_summary.get("models"), list) else [],
    }

