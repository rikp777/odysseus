"""OpenAI billing adapter."""

from __future__ import annotations

from decimal import Decimal
from typing import Any, Dict

import httpx

from src.billing.adapters.common import (
    _billing_month_bounds,
    _estimate_provider_model_cost,
    _iter_usage_results,
    _model_billing_amount,
    _paged_get_json,
)
from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
    int_or_zero as _int_or_zero,
    money as _money,
    stored_money as _stored_money,
    utc_now_iso as _utc_now_iso,
)


_OPENAI_COSTS_URL = "https://api.openai.com/v1/organization/costs"
_OPENAI_COMPLETIONS_USAGE_URL = "https://api.openai.com/v1/organization/usage/completions"


def _openai_costs_total(pages: Any) -> tuple[Decimal, list[Dict[str, Any]]]:
    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    for result in _iter_usage_results(pages):
        amount = result.get("amount") if isinstance(result.get("amount"), dict) else {}
        value = _decimal_or_none(amount.get("value")) or Decimal("0")
        total += value
        line_item = str(result.get("line_item") or "OpenAI costs").strip()
        items.append({
            "id": line_item.lower().replace(" ", "-")[:80] or "openai-costs",
            "label": line_item,
            "amount": _money(value),
            "display": f"${_money(value)}",
            "currency": str(amount.get("currency") or "usd").upper(),
            "project_id": str(result.get("project_id") or ""),
        })
    return total, items


def _openai_completions_summary(pages: Any) -> Dict[str, Any]:
    total = Decimal("0")
    items: list[Dict[str, Any]] = []
    models: Dict[str, Dict[str, Any]] = {}

    for result in _iter_usage_results(pages):
        model_label = str(result.get("model") or "OpenAI model").strip()
        input_tokens = _int_or_zero(result.get("input_tokens"))
        output_tokens = _int_or_zero(result.get("output_tokens"))
        requests = _int_or_zero(result.get("num_model_requests"))
        cost = _estimate_provider_model_cost(
            "openai",
            model_label,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )
        if cost is None:
            continue
        total += cost
        item = {
            "id": model_label.lower(),
            "label": model_label,
            "model": model_label,
            "amount": _stored_money(cost) or "0.000000",
            "display": f"${_money(cost)}",
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": input_tokens + output_tokens,
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
        model["input_tokens"] += input_tokens
        model["output_tokens"] += output_tokens
        model["total_tokens"] += input_tokens + output_tokens

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
        "provider": "openai",
        "provider_label": "OpenAI",
        "label": "OpenAI API model usage",
        "source_kind": "provider_model_billing",
        "source_label": "OpenAI usage estimate",
        "items": items,
        "models": model_rows,
    }


def _fetch_openai_billing(token: str) -> Dict[str, Any]:
    start, end = _billing_month_bounds()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    cost_pages = _paged_get_json(
        _OPENAI_COSTS_URL,
        headers=headers,
        params={
            "start_time": int(start.timestamp()),
            "end_time": int(end.timestamp()),
            "bucket_width": "1d",
            "limit": 180,
        },
    )
    payload: Dict[str, Any] = {"costs": cost_pages}
    try:
        payload["completions_usage"] = _paged_get_json(
            _OPENAI_COMPLETIONS_USAGE_URL,
            headers=headers,
            params={
                "start_time": int(start.timestamp()),
                "end_time": int(end.timestamp()),
                "bucket_width": "1d",
                "limit": 31,
                "group_by": ["model"],
            },
        )
    except httpx.HTTPStatusError as exc:
        status_code = exc.response.status_code if exc.response is not None else "unknown"
        payload["_odysseus_model_billing_error"] = f"OpenAI usage API returned {status_code}"
    except httpx.RequestError as exc:
        payload["_odysseus_model_billing_error"] = str(exc) or "OpenAI usage API request failed"
    except Exception:
        payload["_odysseus_model_billing_error"] = "OpenAI usage API returned an unreadable response"
    return payload


def _openai_payload(raw: Dict[str, Any]) -> Dict[str, Any]:
    amount, cost_items = _openai_costs_total(raw.get("costs"))
    payload = {
        "amount_decimal": amount,
        "month_to_date_usage": _money(amount),
        "generated_at": _utc_now_iso(),
        "cost_items": cost_items,
    }
    usage_summary = _openai_completions_summary(raw.get("completions_usage"))
    model_amount = _model_billing_amount(usage_summary)
    if model_amount is not None and (model_amount > 0 or usage_summary.get("models")):
        payload.update({
            "model_amount_decimal": model_amount,
            "model_display": f"${_money(model_amount)}",
            "model_spend_label": str(usage_summary.get("label") or "OpenAI API model usage"),
            "model_spend_source": str(usage_summary.get("source_label") or "OpenAI usage estimate"),
            "model_spend_items": usage_summary.get("items") if isinstance(usage_summary.get("items"), list) else [],
            "model_spend_models": usage_summary.get("models") if isinstance(usage_summary.get("models"), list) else [],
        })
    if raw.get("_odysseus_model_billing_error"):
        payload["model_spend_error"] = str(raw.get("_odysseus_model_billing_error") or "")
    return payload

