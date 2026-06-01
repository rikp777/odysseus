from decimal import Decimal

from src import billing_usage


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

    assert "Cloud model budget reached" in reason
    assert "$1.25" in reason
    assert billing_usage.local_budget_block_reason("http://127.0.0.1:11434/v1/chat/completions") is None
