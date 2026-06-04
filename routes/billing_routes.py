"""Cloud billing status routes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any, Dict, Optional

from fastapi import APIRouter, Request

from core.middleware import require_admin
from src.billing import charts as _billing_charts
from src.billing import events as _billing_events
from src.billing import history as _billing_history
from src.billing import service as _billing_service
from src.billing.accounts import billing_accounts as _billing_accounts
from src.billing.common import (
    decimal_or_none as _decimal_or_none,
    decimal_or_zero as _decimal_or_zero,
    money as _money,
    utc_now_iso as _utc_now_iso,
)
from src.billing.spend_sources import apply_primary_spend_source as _apply_primary_spend_source
from src.billing.providers import (
    _PROVIDERS,
    _normalized_provider,
    _provider_meta,
    provider_catalog as _provider_catalog,
)
from src.billing.status import BillingStatusService
from src.billing_usage import get_session_usage_summary, get_usage_summary
from src.secret_storage import decrypt as _decrypt_secret
from src.settings import load_settings as _load_settings


_CACHE: Dict[str, Any] = {
    "fingerprint": "",
    "expires_at": 0.0,
    "payload": None,
}
BILLING_HISTORY_FILE = _billing_history.DEFAULT_BILLING_HISTORY_FILE
BILLING_EVENTS_FILE = _billing_events.DEFAULT_BILLING_EVENTS_FILE
MAX_BILLING_HISTORY_SAMPLES = _billing_history.MAX_BILLING_HISTORY_SAMPLES
_BILLING_MONTH_RE = _billing_history.BILLING_MONTH_RE


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


def _public_usage_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    payload = dict(summary)
    payload.pop("amount_decimal", None)
    payload.pop("projected_decimal", None)
    return payload


def _attach_local_usage(payload: Dict[str, Any], *, period: str = "month") -> Dict[str, Any]:
    payload["local_usage"] = _local_usage_payload(period)
    return payload


def _attach_budget_safety(status: Dict[str, Any], *, sync_events: bool = True) -> Dict[str, Any]:
    settings = _load_settings()
    enforcement_enabled = settings.get("cloud_billing_budget_enforcement_enabled") is not False
    status["budget_state"] = _billing_events.budget_state_from_status(
        status,
        enforcement_enabled=enforcement_enabled,
    )
    if sync_events:
        status["budget_events"] = _billing_events.sync_billing_events_from_status(
            status,
            enforcement_enabled=enforcement_enabled,
            event_file=BILLING_EVENTS_FILE,
        )
    else:
        status["budget_events"] = _billing_events.recent_billing_events(event_file=BILLING_EVENTS_FILE)
    return status


def _clamp_refresh_seconds(value: Any) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = 900
    return max(60, min(parsed, 3600))


def _token_fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


_billing_scope = _billing_history.billing_scope
_billing_month = _billing_history.billing_month
_billing_month_label = _billing_history.billing_month_label
_normalized_history_spend_source = _billing_history.normalized_history_spend_source
_normalized_history_spend_scope = _billing_history.normalized_history_spend_scope
_history_source_label = _billing_history.history_source_label


def _record_billing_sample(status: Dict[str, Any], *, forced_provider: Optional[str] = None) -> None:
    _billing_history.record_billing_sample(
        status,
        forced_provider=forced_provider,
        history_file=BILLING_HISTORY_FILE,
        max_samples=MAX_BILLING_HISTORY_SAMPLES,
    )


def _history_items_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
) -> list[Dict[str, Any]]:
    return _billing_history.history_items_for_month(
        month=month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=BILLING_HISTORY_FILE,
    )


def _history_for_month(
    *,
    month: str,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
) -> list[Dict[str, Any]]:
    return _billing_history.history_for_month(
        month=month,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=BILLING_HISTORY_FILE,
    )


def _history_for_current_month(
    *,
    scope: str,
    spend_source: str = "provider_billing",
    spend_scope: str = "provider_account",
    now: Optional[datetime] = None,
) -> list[Dict[str, Any]]:
    return _billing_history.history_for_current_month(
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=BILLING_HISTORY_FILE,
        now=now,
    )


def _history_months_for_series(
    *,
    scope: str,
    spend_source: str,
    spend_scope: str,
) -> list[str]:
    return _billing_history.history_months_for_series(
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=BILLING_HISTORY_FILE,
    )


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
        provider_amount = sum(
            (_decimal_or_zero(item.get("amount")) for item in accounts if isinstance(item, dict)),
            Decimal("0"),
        )
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
        "provider_display": (
            f"${_money(provider_amount)}" if provider_amount is not None and provider_amount > 0 else ""
        ),
        "spend_source": spend_source,
        "spend_scope": spend_scope,
        "source_label": source_label,
        "accounts": [dict(item) for item in accounts if isinstance(item, dict)],
        "history_only": True,
    }


def build_spending_graph_payload(
    status: Dict[str, Any],
    *,
    forced_provider: Optional[str] = None,
    now: Optional[datetime] = None,
    month: str = "",
) -> Dict[str, Any]:
    return _billing_charts.build_spending_graph_payload(
        status,
        forced_provider=forced_provider,
        now=now,
        month=month,
        history_file=BILLING_HISTORY_FILE,
    )


def billing_chart_markdown(chart: Dict[str, Any]) -> str:
    return _billing_charts.billing_chart_markdown(chart)


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


def _fetch_account_spend(
    account: Dict[str, Any],
    *,
    warning: Optional[Decimal],
    warning_usd: Optional[str],
    refresh_seconds: int,
) -> Dict[str, Any]:
    return _billing_service.fetch_account_spend(
        account,
        warning=warning,
        warning_usd=warning_usd,
        refresh_seconds=refresh_seconds,
        providers=_PROVIDERS,
        decrypt_secret=_decrypt_secret,
    )


def _billing_status_service() -> BillingStatusService:
    return BillingStatusService(
        cache=_CACHE,
        load_settings=_load_settings,
        billing_accounts=_billing_accounts,
        normalized_provider=_normalized_provider,
        provider_meta=_provider_meta,
        decrypt_secret=_decrypt_secret,
        token_fingerprint=_token_fingerprint,
        empty_payload=_empty_payload,
        local_only_payload=_local_only_payload,
        attach_local_usage=_attach_local_usage,
        fetch_account_spend=_fetch_account_spend,
        apply_primary_spend_source=_apply_primary_spend_source,
        clamp_refresh_seconds=_clamp_refresh_seconds,
    )


def _monthly_spend(request: Request, *, refresh: bool, forced_provider: Optional[str] = None) -> Dict[str, Any]:
    require_admin(request)
    return get_monthly_spend_status(refresh=refresh, forced_provider=forced_provider)


def get_monthly_spend_status(*, refresh: bool = False, forced_provider: Optional[str] = None) -> Dict[str, Any]:
    status = _billing_status_service().monthly_spend_status(
        refresh=refresh,
        forced_provider=forced_provider,
    )
    return _attach_budget_safety(status)


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
        _attach_budget_safety(status)
    elif not is_current_month:
        status = _history_month_status(
            month=selected_month,
            forced_provider=forced_provider,
            spend_source=_normalized_history_spend_source(spend_source),
            spend_scope=_normalized_history_spend_scope(spend_scope),
        )
        _attach_budget_safety(status, sync_events=False)
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

    @router.get("/session/{session_id}/usage")
    def session_usage(session_id: str, request: Request) -> Dict[str, Any]:
        require_admin(request)
        return _public_usage_summary(get_session_usage_summary(session_id=session_id))

    @router.get("/providers")
    def billing_providers(request: Request) -> Dict[str, Any]:
        require_admin(request)
        return {"providers": _provider_catalog(_PROVIDERS)}

    @router.get("/events")
    def billing_events(request: Request, limit: int = 12) -> Dict[str, Any]:
        require_admin(request)
        return {"events": _billing_events.recent_billing_events(limit=limit, event_file=BILLING_EVENTS_FILE)}

    @router.get("/{provider}/monthly-spend")
    def provider_monthly_spend(provider: str, request: Request, refresh: bool = False) -> Dict[str, Any]:
        return _monthly_spend(request, refresh=refresh, forced_provider=provider)

    return router
