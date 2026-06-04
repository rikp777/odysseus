from datetime import datetime, timezone

from src.billing import events


def test_billing_events_dedupe_and_redact_secret_details(tmp_path):
    event_file = tmp_path / "billing_events.json"
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)

    first = events.record_billing_event(
        kind="provider_billing_check_failed",
        severity="warning",
        title="Provider check failed",
        message="Billing API returned 403",
        source="digitalocean",
        details={
            "provider": "digitalocean",
            "api_token": "secret",
            "nested": {"password": "hidden", "status": "upstream_error"},
        },
        event_file=event_file,
        now=now,
    )
    second = events.record_billing_event(
        kind="provider_billing_check_failed",
        severity="warning",
        title="Provider check failed",
        message="Billing API returned 403",
        source="digitalocean",
        details={
            "provider": "digitalocean",
            "api_token": "secret",
            "nested": {"password": "hidden", "status": "upstream_error"},
        },
        event_file=event_file,
        now=now,
    )

    stored = events.read_billing_events(event_file)
    assert len(stored) == 1
    assert first["id"] == second["id"]
    assert second["count"] == 2
    assert "api_token" not in second["details"]
    assert "password" not in second["details"]["nested"]
    assert second["details"]["nested"]["status"] == "upstream_error"


def test_budget_state_does_not_block_on_provider_account_totals():
    state = events.budget_state_from_status(
        {
            "enabled": True,
            "configured": True,
            "amount": "12.00",
            "display": "$12.00",
            "limit_usd": "10.00",
            "over_limit": True,
            "spend_source": "provider_billing",
            "spend_scope": "provider_account",
        },
        enforcement_enabled=True,
    )

    assert state["over_limit"] is True
    assert state["spend_scope"] == "provider_account"
    assert state["block_remote_models"] is False
    assert state["block_code"] == "ok"


def test_sync_billing_events_records_threshold_provider_and_unpriced_usage(tmp_path):
    event_file = tmp_path / "billing_events.json"

    recent = events.sync_billing_events_from_status(
        {
            "enabled": True,
            "configured": True,
            "amount": "1.25",
            "display": "$1.25",
            "warning_usd": "1.00",
            "limit_usd": "2.00",
            "over_warning": True,
            "over_limit": False,
            "spend_source": "usage_ledger",
            "spend_scope": "model_usage",
            "source_label": "Usage ledger",
            "provider_health": [
                {
                    "provider": "digitalocean",
                    "provider_label": "DigitalOcean",
                    "account_id": "do-main",
                    "configured": True,
                    "ok": False,
                    "status": "upstream_error",
                    "status_label": "Failed",
                    "last_error": "DigitalOcean billing API returned 403",
                }
            ],
            "local_usage": {
                "events": 3,
                "known_cost_events": 2,
                "unknown_cost_events": 1,
            },
        },
        event_file=event_file,
    )

    kinds = {event["kind"] for event in recent}
    assert "budget_warning_reached" in kinds
    assert "provider_billing_check_failed" in kinds
    assert "model_cost_unknown" in kinds
    assert all("token" not in str(event).lower() for event in recent)
