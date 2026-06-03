"""Shared context for billing chart builders."""

from __future__ import annotations

from calendar import monthrange
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, Optional

from src.billing import history as _history


@dataclass(frozen=True)
class SpendingGraphContext:
    current: datetime
    selected_month: str
    month_reference: datetime
    period: str
    is_current_month: bool
    days_in_month: int
    elapsed_days: int
    projected: Decimal
    scope: str
    spend_source: str
    spend_scope: str
    available_months: list[str]
    previous_month: str
    next_month: str


def build_spending_graph_context(
    status: Dict[str, Any],
    *,
    amount: Decimal,
    forced_provider: Optional[str] = None,
    now: Optional[datetime] = None,
    month: str = "",
    history_file: Path = _history.DEFAULT_BILLING_HISTORY_FILE,
) -> SpendingGraphContext:
    current = now or datetime.now(timezone.utc)
    selected_month = _history.billing_month(month or status.get("month"), now=current)
    month_reference = _history.billing_month_datetime(selected_month)
    period = str(status.get("period") or "month")
    is_current_month = selected_month == current.strftime("%Y-%m")
    days_in_month = monthrange(month_reference.year, month_reference.month)[1]
    elapsed_days = max(1, current.day if is_current_month else days_in_month)
    projected = (
        (amount / Decimal(elapsed_days)) * Decimal(days_in_month)
        if period == "month" and is_current_month and amount > 0
        else amount
    )
    scope = _history.billing_scope(forced_provider)
    spend_source = _history.history_spend_source(status)
    spend_scope = _history.history_spend_scope(status)
    available_months = _history.history_months_for_series(
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        history_file=history_file,
    )
    current_month = current.strftime("%Y-%m")
    if is_current_month and selected_month not in available_months:
        available_months = sorted([*available_months, selected_month])
    previous_month, next_month = _history.history_month_navigation(
        selected_month,
        available_months,
        current_month=current_month,
    )
    return SpendingGraphContext(
        current=current,
        selected_month=selected_month,
        month_reference=month_reference,
        period=period,
        is_current_month=is_current_month,
        days_in_month=days_in_month,
        elapsed_days=elapsed_days,
        projected=projected,
        scope=scope,
        spend_source=spend_source,
        spend_scope=spend_scope,
        available_months=available_months,
        previous_month=previous_month,
        next_month=next_month,
    )
