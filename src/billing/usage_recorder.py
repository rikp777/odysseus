"""Safe wrappers for recording model usage from request flows."""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from src.billing_usage import record_model_usage_from_metrics


def record_model_usage_safely(
    *,
    owner: Optional[str],
    session_id: Optional[str],
    message_id: Optional[str],
    endpoint_url: str,
    model: str,
    metrics: Optional[Dict[str, Any]],
    logger: Optional[logging.Logger] = None,
) -> None:
    """Record a usage event without letting billing failures break chat."""
    try:
        record_model_usage_from_metrics(
            owner=owner,
            session_id=session_id,
            message_id=message_id,
            endpoint_url=endpoint_url,
            model=model,
            metrics=metrics,
        )
    except Exception as exc:
        if logger:
            logger.warning("Failed to record model usage for billing ledger: %s", exc)
