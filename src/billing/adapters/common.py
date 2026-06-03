"""Shared helpers for provider billing adapters."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

import httpx

from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
)


def _billing_month_bounds() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc).replace(microsecond=0)
    start = now.replace(day=1, hour=0, minute=0, second=0)
    return start, now


def _paged_get_json(
    url: str,
    *,
    headers: Dict[str, str],
    params: Any,
    timeout: float = 15.0,
) -> list[Dict[str, Any]]:
    pages: list[Dict[str, Any]] = []
    page: Optional[str] = None
    while True:
        request_params = list(params) if isinstance(params, list) else dict(params)
        if page:
            if isinstance(request_params, list):
                request_params.append(("page", page))
            else:
                request_params["page"] = page
        response = httpx.get(url, headers=headers, params=request_params, timeout=timeout)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("paginated provider response was not an object")
        pages.append(payload)
        next_page = str(payload.get("next_page") or "").strip()
        if not payload.get("has_more") or not next_page:
            break
        page = next_page
    return pages


def _iter_usage_results(pages: Any):
    if isinstance(pages, dict):
        pages = [pages]
    if not isinstance(pages, list):
        return
    for page in pages:
        if not isinstance(page, dict):
            continue
        for bucket in page.get("data") or []:
            if not isinstance(bucket, dict):
                continue
            for result in bucket.get("results") or []:
                if isinstance(result, dict):
                    yield result


def _estimate_provider_model_cost(
    provider: str,
    model: str,
    *,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_write_5m_tokens: int = 0,
    cache_write_1h_tokens: int = 0,
    cache_read_tokens: int = 0,
) -> Optional[Decimal]:
    try:
        from src.model_pricing import _model_pricing_for_provider
        pricing = _model_pricing_for_provider(provider, model)
    except Exception:
        pricing = None
    if not pricing:
        return None

    denominator = Decimal("1000000")
    total = Decimal("0")
    if pricing.get("input_usd_per_unit") is not None:
        total += (Decimal(max(input_tokens, 0)) / denominator) * _decimal_or_zero(
            pricing.get("input_usd_per_unit")
        )
    if pricing.get("output_usd_per_unit") is not None:
        total += (Decimal(max(output_tokens, 0)) / denominator) * _decimal_or_zero(
            pricing.get("output_usd_per_unit")
        )
    if pricing.get("cache_write_5m_usd_per_unit") is not None:
        total += (Decimal(max(cache_write_5m_tokens, 0)) / denominator) * _decimal_or_zero(
            pricing.get("cache_write_5m_usd_per_unit")
        )
    if pricing.get("cache_write_1h_usd_per_unit") is not None:
        total += (Decimal(max(cache_write_1h_tokens, 0)) / denominator) * _decimal_or_zero(
            pricing.get("cache_write_1h_usd_per_unit")
        )
    if pricing.get("cache_read_usd_per_unit") is not None:
        total += (Decimal(max(cache_read_tokens, 0)) / denominator) * _decimal_or_zero(
            pricing.get("cache_read_usd_per_unit")
        )
    return total


def _model_billing_amount(summary: Any) -> Optional[Decimal]:
    if not isinstance(summary, dict):
        return None
    return _decimal_or_none(summary.get("amount_decimal") or summary.get("amount"))

