"""DigitalOcean billing adapter."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict

import httpx

from src.billing.adapters.common import _model_billing_amount
from src.billing.common import (
    decimal_or_zero as _decimal_or_zero,
    int_or_zero as _int_or_zero,
    money as _money,
)


_DIGITALOCEAN_BALANCE_URL = "https://api.digitalocean.com/v2/customers/my/balance"
_DIGITALOCEAN_ACCOUNT_URL = "https://api.digitalocean.com/v2/account"
_DIGITALOCEAN_BILLING_INSIGHTS_URL = (
    "https://api.digitalocean.com/v2/billing/{account_urn}/insights/{start_date}/{end_date}"
)
_DIGITALOCEAN_MODEL_RE = re.compile(
    r"^(?P<model>.+?)\s+(?:Cache\s+Read\s+Input|Input|Output)\s+tokens\b",
    re.IGNORECASE,
)


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

