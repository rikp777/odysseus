"""Billing history storage and month helpers."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from core.atomic_io import atomic_write_json
from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
    float_money as _float_money,
    money as _money,
)
from src.billing.providers import normalized_provider


DEFAULT_BILLING_HISTORY_FILE = Path("data/billing_history.json")
MAX_BILLING_HISTORY_SAMPLES = 720
BILLING_MONTH_RE = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def read_billing_history(history_file: Path = DEFAULT_BILLING_HISTORY_FILE) -> list[Dict[str, Any]]:
    try:
        with open(history_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            return [item for item in data if isinstance(item, dict)]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return []


def write_billing_history(
    samples: list[Dict[str, Any]],
    *,
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
    max_samples: int = MAX_BILLING_HISTORY_SAMPLES,
) -> None:
    atomic_write_json(str(history_file), samples[-max_samples:], indent=2)


def account_history_snapshot(account: Dict[str, Any]) -> Dict[str, Any]:
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
            "model_spend_models": (
                account.get("model_spend_models")
                if isinstance(account.get("model_spend_models"), list)
                else []
            ),
        })
    return snapshot


def billing_scope(forced_provider: Optional[str] = None) -> str:
    return normalized_provider(forced_provider) if forced_provider else "all"


def billing_month(value: Any = "", *, now: Optional[datetime] = None) -> str:
    raw = str(value or "").strip()
    if BILLING_MONTH_RE.fullmatch(raw):
        return raw
    current = now or datetime.now(timezone.utc)
    return current.strftime("%Y-%m")


def billing_month_datetime(month: str) -> datetime:
    normalized = billing_month(month)
    return datetime(int(normalized[:4]), int(normalized[5:7]), 1, tzinfo=timezone.utc)


def billing_month_label(month: str) -> str:
    return billing_month_datetime(month).strftime("%B %Y")


def shift_billing_month(month: str, offset: int) -> str:
    reference = billing_month_datetime(month)
    month_index = (reference.year * 12) + reference.month - 1 + offset
    year = month_index // 12
    shifted_month = (month_index % 12) + 1
    return f"{year:04d}-{shifted_month:02d}"


def history_spend_source(status: Dict[str, Any]) -> str:
    return str(status.get("spend_source") or "provider_billing").strip().lower() or "provider_billing"


def history_spend_scope(status: Dict[str, Any]) -> str:
    return str(status.get("spend_scope") or "provider_account").strip().lower() or "provider_account"


def normalized_history_spend_source(value: Any) -> str:
    source = str(value or "").strip().lower()
    return source if source in {"provider_billing", "provider_model_billing", "usage_ledger"} else "provider_billing"


def normalized_history_spend_scope(value: Any) -> str:
    scope = str(value or "").strip().lower()
    return scope if scope in {"provider_account", "model_usage"} else "provider_account"


def history_source_label(spend_source: str) -> str:
    if spend_source == "provider_model_billing":
        return "Provider model billing"
    if spend_source == "usage_ledger":
        return "Usage ledger"
    return "Provider billing"


def history_item_matches_series(
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
        # Older history samples predate explicit spend_source/spend_scope and
        # mostly represented provider account totals. Labels that look like
        # model spend are too ambiguous to reuse safely because they can leak
        # old partial/derived points into either account or AI-only graphs.
        if "model" in legacy_label:
            return False
        return spend_scope == "provider_account" and spend_source == "provider_billing"
    return item_scope == spend_scope and item_source == spend_source


def history_sample_day(timestamp: Any) -> str:
    raw = str(timestamp or "").strip()
    if not raw:
        return ""
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return raw[:10] if len(raw) >= 10 else ""
    return parsed.astimezone(timezone.utc).strftime("%Y-%m-%d")


def collapse_history_to_daily_latest(
    points: list[Dict[str, Any]],
    *,
    now: datetime,
) -> list[Dict[str, Any]]:
    daily: Dict[str, Dict[str, Any]] = {}
    for point in points:
        day = history_sample_day(point.get("timestamp"))
        if not day:
            continue
        current = daily.get(day)
        if current is None or str(point.get("timestamp") or "") >= str(current.get("timestamp") or ""):
            daily[day] = point

    collapsed = [daily[key] for key in sorted(daily)]
    if not collapsed:
        return []

    month = now.strftime("%Y-%m")
    first_day = history_sample_day(collapsed[0].get("timestamp"))
    if first_day > f"{month}-01" and _decimal_or_zero(collapsed[0].get("amount")) > 0:
        collapsed.insert(0, {
            "timestamp": f"{month}-01T00:00:00Z",
            "amount": 0.0,
            "display": "$0.00",
            "synthetic": True,
        })
    return collapsed


def record_billing_sample(
    status: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
    max_samples: int = MAX_BILLING_HISTORY_SAMPLES,
    now: Optional[datetime] = None,
) -> None:
    amount = _decimal_or_none(status.get("amount"))
    if amount is None:
        return

    recorded_at = now or datetime.now(timezone.utc)
    scope = billing_scope(forced_provider)
    spend_source = history_spend_source(status)
    spend_scope = history_spend_scope(status)
    sample = {
        "timestamp": recorded_at.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "month": recorded_at.strftime("%Y-%m"),
        "scope": scope,
        "spend_source": spend_source,
        "spend_scope": spend_scope,
        "amount": _money(amount),
        "display": f"${_money(amount)}",
        "currency": status.get("currency") or "USD",
        "provider": status.get("provider") or "multiple",
        "provider_label": status.get("provider_label") or "Cloud",
        "accounts": [account_history_snapshot(item) for item in status.get("accounts", []) if isinstance(item, dict)],
    }

    samples = read_billing_history(history_file)
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
    write_billing_history(samples, history_file=history_file, max_samples=max_samples)


def history_items_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
) -> list[Dict[str, Any]]:
    normalized_source = normalized_history_spend_source(spend_source)
    normalized_scope = normalized_history_spend_scope(spend_scope)
    items = []
    for item in read_billing_history(history_file):
        if item.get("month") != month or item.get("scope") != scope:
            continue
        if not history_item_matches_series(item, spend_source=normalized_source, spend_scope=normalized_scope):
            continue
        items.append(item)
    return sorted(items, key=lambda item: str(item.get("timestamp") or ""))


def history_points_from_items(items: list[Dict[str, Any]]) -> list[Dict[str, Any]]:
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


def history_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
) -> list[Dict[str, Any]]:
    current = billing_month_datetime(month)
    points = history_points_from_items(history_items_for_month(
        month=month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=history_file,
    ))
    return collapse_history_to_daily_latest(points, now=current)


def history_for_current_month(
    *,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
    now: Optional[datetime] = None,
) -> list[Dict[str, Any]]:
    current = now or datetime.now(timezone.utc)
    return history_for_month(
        month=current.strftime("%Y-%m"),
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=history_file,
    )


def history_months_for_series(
    *,
    scope: str,
    spend_source: str,
    spend_scope: str,
    history_file: Path = DEFAULT_BILLING_HISTORY_FILE,
) -> list[str]:
    months = set()
    normalized_source = normalized_history_spend_source(spend_source)
    normalized_scope = normalized_history_spend_scope(spend_scope)
    for item in read_billing_history(history_file):
        month = str(item.get("month") or "").strip()
        if not BILLING_MONTH_RE.fullmatch(month) or item.get("scope") != scope:
            continue
        if history_item_matches_series(item, spend_source=normalized_source, spend_scope=normalized_scope):
            months.add(month)
    return sorted(months)


def history_month_navigation(
    selected_month: str,
    available_months: list[str],
    *,
    current_month: str,
) -> tuple[str, str]:
    months = sorted({month for month in available_months if BILLING_MONTH_RE.fullmatch(month)} | {selected_month})
    lower_bound = months[0] if months else selected_month
    previous = shift_billing_month(selected_month, -1)
    next_month = shift_billing_month(selected_month, 1)
    if previous < lower_bound and selected_month != current_month:
        previous = ""
    if next_month > current_month:
        next_month = ""
    return previous, next_month
