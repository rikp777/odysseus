"""Billing chart payload builders."""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from src.billing import history as _history
from src.billing.chart_context import build_spending_graph_context
from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
    float_money as _float_money,
    int_or_zero as _int_or_zero,
    money as _money,
    utc_now_iso as _utc_now_iso,
)
from src.billing.providers import normalized_provider


def usage_breakdown(source: Any) -> Dict[str, Any]:
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


def usage_status(usage: Dict[str, Any]) -> str:
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


def chart_usage_payload(local_usage: Any) -> Dict[str, Any]:
    if not isinstance(local_usage, dict):
        return {}
    usage = usage_breakdown(local_usage)
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


def chart_source_note(status: Dict[str, Any], usage: Dict[str, Any]) -> str:
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


def chart_provider_model_accounts(status: Dict[str, Any], group_by: str) -> list[Dict[str, Any]]:
    accounts = []
    for item in status.get("accounts", []):
        if not isinstance(item, dict):
            continue
        provider = str(item.get("provider") or "").strip()
        provider_label = str(item.get("provider_label") or provider or "Provider").strip()
        source_label = str(
            item.get("model_spend_source_label")
            or item.get("model_spend_source")
            or "Provider model billing"
        )
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


def chart_accounts(status: Dict[str, Any]) -> list[Dict[str, Any]]:
    accounts = []
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    group_by = str(status.get("group_by") or "provider").lower()
    if status.get("spend_source") == "provider_model_billing":
        provider_model_accounts = chart_provider_model_accounts(status, group_by)
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
                local_provider_usage[key] = usage_breakdown(item)
    if local_usage and local_usage.get("enabled"):
        if group_by == "model":
            for item in local_usage.get("models", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                usage = usage_breakdown(item)
                accounts.append({
                    "id": item.get("id") or item.get("label") or "model",
                    "label": item.get("label") or item.get("id") or "Model",
                    "provider": "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": usage_status(usage),
                    "error": "",
                    "usage": usage,
                    "source_kind": "usage_ledger",
                    "source_label": "Usage estimate",
                })
        elif group_by == "provider":
            for item in local_usage.get("providers", []):
                amount = _decimal_or_none(item.get("amount")) or Decimal("0")
                usage = usage_breakdown(item)
                accounts.append({
                    "id": "usage-" + str(item.get("id") or item.get("label") or "provider"),
                    "label": str(item.get("label") or item.get("id") or "Provider") + " model usage",
                    "provider": item.get("id") or "local_usage",
                    "provider_label": "Local usage",
                    "amount": _float_money(amount) or 0.0,
                    "display": item.get("display") or f"${_money(amount)}",
                    "ok": True,
                    "status": usage_status(usage),
                    "error": "",
                    "usage": usage,
                    "source_kind": "usage_ledger",
                    "source_label": "Usage estimate",
                })
        elif local_usage.get("events") or not status.get("accounts"):
            amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
            usage = usage_breakdown(local_usage)
            accounts.append({
                "id": "local-model-usage",
                "label": "Tracked model usage",
                "provider": "local_usage",
                "provider_label": "Local usage",
                "amount": _float_money(amount) or 0.0,
                "display": local_usage.get("display") or f"${_money(amount)}",
                "ok": True,
                "status": usage_status(usage),
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
    history_file: Path = _history.DEFAULT_BILLING_HISTORY_FILE,
) -> Dict[str, Any]:
    amount = _decimal_or_none(status.get("amount"))
    local_usage = status.get("local_usage") if isinstance(status.get("local_usage"), dict) else None
    if amount is None and local_usage:
        amount = _decimal_or_none(local_usage.get("amount")) or Decimal("0")
    amount = amount or Decimal("0")
    context = build_spending_graph_context(
        status,
        amount=amount,
        forced_provider=forced_provider,
        now=now,
        month=month,
        history_file=history_file,
    )
    period = context.period
    warning = _decimal_or_none(status.get("warning_usd"))
    limit = _decimal_or_none(status.get("limit_usd"))
    monthly_warning = warning if period == "month" else None
    monthly_limit = limit if period == "month" else None
    daily_warning = warning if period == "day" else None
    daily_limit = limit if period == "day" else None
    history = _history.history_for_month(
        month=context.selected_month,
        scope=context.scope,
        spend_source=context.spend_source,
        spend_scope=context.spend_scope,
        history_file=history_file,
    )
    group_by = str(status.get("group_by") or "provider").lower()
    usage_payload = chart_usage_payload(local_usage)
    title = (
        "Model Spend"
        if status.get("spend_scope") == "model_usage" or status.get("provider") == "local_usage"
        else "Cloud Account Spend"
    )
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
            else (
                f"{_history.billing_month_label(context.selected_month)} month-to-date"
                if context.is_current_month
                else _history.billing_month_label(context.selected_month)
            )
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
        "projected": _float_money(context.projected) or 0.0,
        "projected_display": f"${_money(context.projected)}",
        "remaining_limit": _float_money(max(limit - amount, Decimal("0"))) if limit is not None else None,
        "remaining_limit_display": f"${_money(max(limit - amount, Decimal('0')))}" if limit is not None else "",
        "days_elapsed": context.elapsed_days,
        "days_in_month": context.days_in_month,
        "updated_at": status.get("updated_at") or _utc_now_iso(),
        "cached": bool(status.get("cached", False)),
        "provider_label": status.get("provider_label") or "Cloud",
        "provider_short_label": status.get("provider_short_label") or "ALL",
        "spend_source": status.get("spend_source") or "provider_billing",
        "spend_scope": status.get("spend_scope") or "provider_account",
        "source_label": status.get("source_label") or "",
        "provider_total": _float_money(provider_amount) if expose_provider_total else None,
        "provider_total_display": (
            f"${_money(provider_amount)}" if expose_provider_total and provider_amount is not None else ""
        ),
        "period": period,
        "month": context.selected_month,
        "month_label": _history.billing_month_label(context.selected_month),
        "is_current_month": context.is_current_month,
        "available_months": context.available_months,
        "previous_month": context.previous_month,
        "next_month": context.next_month,
        "scope": context.scope,
        "provider_query": normalized_provider(forced_provider) if forced_provider else "",
        "history_only": bool(status.get("history_only", False)),
        "group_by": group_by,
        "local_usage": local_usage or {},
        "usage": usage_payload,
        "source_note": chart_source_note(status, usage_payload),
        "accounts": chart_accounts(status),
        "history": history,
        "notice": notice,
    }


def billing_chart_markdown(chart: Dict[str, Any]) -> str:
    payload = json.dumps(chart, ensure_ascii=False, separators=(",", ":"))
    return f"```billing-chart\n{payload}\n```"
