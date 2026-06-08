from decimal import Decimal
from datetime import datetime
from types import SimpleNamespace

from src import billing_usage


def _usage_row(
    *,
    message_id="msg-1",
    provider="openai",
    model="gpt-4o-mini",
    input_tokens=100,
    output_tokens=50,
    total_cost_usd="0.001000",
    created_at=None,
):
    return SimpleNamespace(
        message_id=message_id,
        provider=provider,
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        total_tokens=input_tokens + output_tokens,
        total_cost_usd=total_cost_usd,
        created_at=created_at or datetime(2026, 6, 4, 12, 0, 0),
    )


def test_estimate_usage_cost_uses_provider_pricing(monkeypatch):
    monkeypatch.setattr(
        billing_usage,
        "_pricing_for",
        lambda endpoint, model: {
            "provider": "example",
            "currency": "USD",
            "unit": "1M tokens",
            "input_usd_per_unit": 2.0,
            "output_usd_per_unit": 6.0,
        },
    )

    result = billing_usage.estimate_usage_cost(
        "https://api.example.test/v1/chat/completions",
        "example-model",
        input_tokens=500_000,
        output_tokens=250_000,
    )

    assert result["provider"] == "example"
    assert result["input_cost_usd"] == "1.000000"
    assert result["output_cost_usd"] == "1.500000"
    assert result["total_cost_usd"] == "2.500000"
    assert result["known_cost"] is True


def test_usage_summary_from_rows_groups_costs_and_unknown_events(monkeypatch):
    monkeypatch.setattr(
        billing_usage,
        "load_settings",
        lambda: {"cloud_billing_usage_ledger_enabled": True},
    )
    rows = [
        _usage_row(message_id="msg-1", total_cost_usd="0.001000"),
        _usage_row(message_id="msg-1", provider="anthropic", model="claude", total_cost_usd=None),
        _usage_row(message_id="msg-2", total_cost_usd="0.002000"),
    ]

    summary = billing_usage._usage_summary_from_rows(rows, period="session")
    messages = billing_usage._message_usage_summaries(rows)

    assert summary["period"] == "session"
    assert summary["amount"] == "0.003000"
    assert summary["display"] == "$0.0030"
    assert summary["events"] == 3
    assert summary["known_cost_events"] == 2
    assert summary["unknown_cost_events"] == 1
    assert summary["total_tokens"] == 450
    assert messages[0]["message_id"] == "msg-1"
    assert messages[0]["provider"] == "multiple"
    assert messages[0]["amount"] == "0.001000"
    assert messages[0]["display"] == "$0.0010"
    assert messages[0]["unknown_cost_events"] == 1


def test_record_model_usage_from_metrics_prefers_ledger_source(monkeypatch):
    calls = []
    monkeypatch.setattr(billing_usage, "record_model_usage", lambda **kwargs: calls.append(kwargs) or "event-1")

    event_id = billing_usage.record_model_usage_from_metrics(
        owner="alex",
        session_id=None,
        message_id="logbook:msg",
        endpoint_url="https://api.openai.com/v1/chat/completions",
        model="gpt-4o-mini",
        metrics={
            "input_tokens": 12,
            "output_tokens": 5,
            "model": "gpt-4o-mini",
            "usage_source": "real",
            "ledger_source": "logbook_ai:extract_all",
        },
    )

    assert event_id == "event-1"
    assert calls[0]["source"] == "logbook_ai:extract_all"


def test_estimate_usage_cost_records_unknown_provider_without_cost(monkeypatch):
    monkeypatch.setattr(billing_usage, "_pricing_for", lambda endpoint, model: None)

    result = billing_usage.estimate_usage_cost(
        "https://api.unknown.example/v1/chat/completions",
        "unknown-model",
        input_tokens=100,
        output_tokens=50,
    )

    assert result["provider"] == "api.unknown.example"
    assert result["total_cost_usd"] is None
    assert result["known_cost"] is False


def test_estimate_usage_cost_uses_openai_catalog():
    result = billing_usage.estimate_usage_cost(
        "https://api.openai.com/v1/chat/completions",
        "gpt-4o-mini-2024-07-18",
        input_tokens=1_000_000,
        output_tokens=500_000,
    )

    assert result["provider"] == "openai"
    assert result["input_cost_usd"] == "0.150000"
    assert result["output_cost_usd"] == "0.300000"
    assert result["total_cost_usd"] == "0.450000"
    assert result["known_cost"] is True


def test_estimate_usage_cost_uses_anthropic_catalog():
    result = billing_usage.estimate_usage_cost(
        "https://api.anthropic.com/v1/messages",
        "claude-sonnet-4-5-20250929",
        input_tokens=1_000_000,
        output_tokens=1_000_000,
    )

    assert result["provider"] == "anthropic"
    assert result["input_cost_usd"] == "3.000000"
    assert result["output_cost_usd"] == "15.000000"
    assert result["total_cost_usd"] == "18.000000"
    assert result["known_cost"] is True


def test_local_budget_blocks_remote_when_daily_limit_is_reached(monkeypatch):
    monkeypatch.setattr(
        billing_usage,
        "load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_budget_enforcement_enabled": True,
            "cloud_billing_usage_ledger_enabled": True,
            "cloud_billing_daily_limit_usd": "1.00",
            "cloud_billing_monthly_limit_usd": "",
        },
    )
    monkeypatch.setattr(
        billing_usage,
        "get_usage_summary",
        lambda period="month", owner=None: {
            "amount_decimal": Decimal("1.25"),
        },
    )

    reason = billing_usage.local_budget_block_reason(
        "https://api.example.test/v1/chat/completions",
        model="remote-model",
    )
    block = billing_usage.local_budget_block(
        "https://api.example.test/v1/chat/completions",
        model="remote-model",
    )

    assert "Cloud model budget reached" in reason
    assert "$1.25" in reason
    assert block["blocked"] is True
    assert block["code"] == "day_limit_reached"
    assert block["period"] == "day"
    assert block["source"] == "usage_ledger"
    assert block["spend_scope"] == "model_usage"
    assert block["model"] == "remote-model"
    assert block["display"] == "$1.25"
    assert block["limit_display"] == "$1.00"
    assert billing_usage.local_budget_block_reason("http://127.0.0.1:11434/v1/chat/completions") is None


def test_local_budget_uses_owner_scope(monkeypatch):
    seen = []
    monkeypatch.setattr(
        billing_usage,
        "load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_budget_enforcement_enabled": True,
            "cloud_billing_usage_ledger_enabled": True,
            "cloud_billing_daily_limit_usd": "",
            "cloud_billing_monthly_limit_usd": "1.00",
        },
    )

    def fake_usage_summary(period="month", owner=None):
        seen.append((period, owner))
        return {"amount_decimal": Decimal("1.25")}

    monkeypatch.setattr(billing_usage, "get_usage_summary", fake_usage_summary)

    reason = billing_usage.local_budget_block_reason(
        "https://api.example.test/v1/chat/completions",
        model="remote-model",
        owner="alice",
    )

    assert "Cloud model budget reached" in reason
    assert seen == [("month", "alice")]
