from types import SimpleNamespace
import json

import pytest
from fastapi import HTTPException

from routes import auth_routes
from routes import billing_routes


class _AuthManager:
    is_configured = True

    def is_admin(self, user):
        return user == "admin"


def _request(user="admin"):
    return SimpleNamespace(
        headers={},
        state=SimpleNamespace(current_user=user),
        app=SimpleNamespace(state=SimpleNamespace(auth_manager=_AuthManager())),
    )


def _endpoint():
    router = billing_routes.setup_billing_routes()
    for route in router.routes:
        if getattr(route, "path", "") == "/api/billing/monthly-spend":
            return route.endpoint
    raise AssertionError("Cloud monthly spend route not found")


def _graph_endpoint():
    router = billing_routes.setup_billing_routes()
    for route in router.routes:
        if getattr(route, "path", "") == "/api/billing/spending-graph":
            return route.endpoint
    raise AssertionError("Cloud spending graph route not found")


def _reset_cache():
    billing_routes._CACHE.update({"fingerprint": "", "expires_at": 0.0, "payload": None})


def _set_digitalocean_fetch(monkeypatch, fetch):
    provider = dict(billing_routes._PROVIDERS["digitalocean"])
    provider["fetch"] = fetch
    monkeypatch.setitem(billing_routes._PROVIDERS, "digitalocean", provider)


def _account(account_id="do-main", provider="digitalocean", token="token", label="Main", enabled=True):
    return {
        "id": account_id,
        "provider": provider,
        "label": label,
        "enabled": enabled,
        "api_token": token,
    }


def _empty_local_usage(period="month"):
    return {
        "enabled": True,
        "period": period,
        "amount": "0.000000",
        "amount_float": 0.0,
        "display": "$0.00",
        "projected": "0.000000",
        "projected_display": "$0.00",
        "events": 0,
        "known_cost_events": 0,
        "unknown_cost_events": 0,
        "input_tokens": 0,
        "output_tokens": 0,
        "total_tokens": 0,
        "providers": [],
        "models": [],
    }


@pytest.fixture(autouse=True)
def clear_billing_cache(monkeypatch):
    _reset_cache()
    monkeypatch.setattr(billing_routes, "_local_usage_payload", _empty_local_usage)
    from src import billing_usage
    monkeypatch.setattr(billing_usage, "local_budget_block_reason", lambda *args, **kwargs: None)
    yield
    _reset_cache()


def test_cloud_monthly_spend_requires_admin():
    with pytest.raises(HTTPException) as exc:
        _endpoint()(_request(user="regular"))
    assert exc.value.status_code == 403


def test_cloud_monthly_spend_disabled_does_not_fetch(monkeypatch):
    calls = []
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": False,
            "cloud_billing_accounts": [_account()],
            "cloud_billing_refresh_seconds": 900,
        },
    )
    _set_digitalocean_fetch(monkeypatch, lambda token: calls.append(token))

    result = _endpoint()(_request())

    assert result["ok"] is False
    assert result["status"] == "disabled"
    assert calls == []


def test_cloud_monthly_spend_reports_missing_token(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [_account(token="")],
            "cloud_billing_refresh_seconds": 900,
        },
    )

    result = _endpoint()(_request())

    assert result["ok"] is False
    assert result["configured"] is False
    assert result["status"] == "missing_token"


def test_cloud_monthly_spend_reports_unsupported_provider(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [_account(provider="examplecloud")],
            "cloud_billing_refresh_seconds": 900,
        },
    )

    result = _endpoint()(_request())

    assert result["ok"] is False
    assert result["status"] == "provider_error"
    assert result["accounts"][0]["provider"] == "examplecloud"
    assert result["accounts"][0]["status"] == "unsupported_provider"


def test_cloud_monthly_spend_success(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [_account()],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_monthly_warning_usd": "10",
            "cloud_billing_monthly_limit_usd": "10",
        },
    )
    _set_digitalocean_fetch(
        monkeypatch,
        lambda token: {
            "month_to_date_usage": "12.346",
            "month_to_date_balance": "12.346",
            "account_balance": "0",
            "generated_at": "2026-06-01T12:00:00Z",
        },
    )

    result = _endpoint()(_request())

    assert result["ok"] is True
    assert result["amount"] == "12.35"
    assert result["display"] == "$12.35"
    assert result["provider"] == "multiple"
    assert result["accounts"][0]["provider"] == "digitalocean"
    assert result["accounts"][0]["provider_label"] == "DigitalOcean"
    assert result["over_warning"] is True
    assert result["over_limit"] is True
    assert result["limit_usd"] == "10.00"
    assert result["refresh_seconds"] == 300


def test_cloud_monthly_spend_sums_multiple_accounts(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [
                _account(account_id="do", token="do-token", label="DigitalOcean"),
                _account(account_id="example", provider="examplecloud", token="ex-token", label="Example"),
            ],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_monthly_warning_usd": "",
        },
    )
    _set_digitalocean_fetch(monkeypatch, lambda token: {"month_to_date_usage": "1.25"})
    monkeypatch.setitem(
        billing_routes._PROVIDERS,
        "examplecloud",
        {
            "label": "ExampleCloud",
            "short_label": "EX",
            "token_hint": "ExampleCloud billing token",
            "fetch": lambda token: {"usage": "2.50"},
            "normalize": lambda balance: {
                "amount_decimal": billing_routes._decimal_or_zero(balance.get("usage")),
                "month_to_date_usage": "2.50",
            },
        },
    )

    result = _endpoint()(_request())

    assert result["ok"] is True
    assert result["amount"] == "3.75"
    assert result["display"] == "$3.75"
    assert result["provider_short_label"] == "ALL"
    assert [item["account_id"] for item in result["accounts"]] == ["do", "example"]


def test_cloud_monthly_spend_can_use_local_usage_without_provider_accounts(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_monthly_limit_usd": "5",
            "cloud_billing_usage_ledger_enabled": True,
        },
    )
    monkeypatch.setattr(
        billing_routes,
        "_local_usage_payload",
        lambda period="month": {
            **_empty_local_usage(period),
            "amount": "1.250000",
            "amount_float": 1.25,
            "display": "$1.25",
            "events": 2,
            "known_cost_events": 2,
        },
    )

    result = _endpoint()(_request())

    assert result["ok"] is True
    assert result["provider"] == "local_usage"
    assert result["amount"] == "1.25"
    assert result["display"] == "$1.25"


def test_cloud_spending_graph_returns_chart_and_records_history(monkeypatch, tmp_path):
    monkeypatch.setattr(billing_routes, "BILLING_HISTORY_FILE", tmp_path / "billing_history.json")
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [
                _account(account_id="do", token="do-token", label="DigitalOcean"),
                _account(account_id="example", provider="examplecloud", token="ex-token", label="Example"),
            ],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_monthly_warning_usd": "3",
            "cloud_billing_monthly_limit_usd": "5",
        },
    )
    _set_digitalocean_fetch(monkeypatch, lambda token: {"month_to_date_usage": "1.25"})
    monkeypatch.setitem(
        billing_routes._PROVIDERS,
        "examplecloud",
        {
            "label": "ExampleCloud",
            "short_label": "EX",
            "token_hint": "ExampleCloud billing token",
            "fetch": lambda token: {"usage": "2.50"},
            "normalize": lambda balance: {
                "amount_decimal": billing_routes._decimal_or_zero(balance.get("usage")),
                "month_to_date_usage": "2.50",
            },
        },
    )

    result = _graph_endpoint()(_request())

    assert result["amount"] == "3.75"
    assert result["chart"]["kind"] == "billing-spend"
    assert result["chart"]["total_display"] == "$3.75"
    assert result["chart"]["limit_display"] == "$5.00"
    assert result["chart"]["source_note"] == "Provider billing totals"
    assert [item["label"] for item in result["chart"]["accounts"]] == ["DigitalOcean", "Example"]
    assert [item["source_label"] for item in result["chart"]["accounts"]] == ["Provider billing", "Provider billing"]
    assert result["markdown"].startswith("```billing-chart\n")
    history_text = (tmp_path / "billing_history.json").read_text(encoding="utf-8")
    assert "do-token" not in history_text
    assert "ex-token" not in history_text


def test_spending_graph_model_group_includes_usage_breakdown(monkeypatch):
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_daily_limit_usd": "2",
            "cloud_billing_usage_ledger_enabled": True,
        },
    )
    monkeypatch.setattr(
        billing_routes,
        "_local_usage_payload",
        lambda period="month": {
            **_empty_local_usage(period),
            "amount": "0.700000",
            "amount_float": 0.7,
            "display": "$0.70",
            "projected": "0.700000",
            "projected_display": "$0.70",
            "events": 3,
            "known_cost_events": 2,
            "unknown_cost_events": 1,
            "input_tokens": 1200,
            "output_tokens": 300,
            "total_tokens": 1500,
            "models": [
                {
                    "id": "gpt-4o",
                    "label": "gpt-4o",
                    "events": 2,
                    "input_tokens": 1000,
                    "output_tokens": 250,
                    "total_tokens": 1250,
                    "amount": 0.65,
                    "display": "$0.65",
                    "known_cost_events": 2,
                },
                {
                    "id": "unknown-model",
                    "label": "unknown-model",
                    "events": 1,
                    "input_tokens": 200,
                    "output_tokens": 50,
                    "total_tokens": 250,
                    "amount": 0.0,
                    "display": "$0.00",
                    "known_cost_events": 0,
                },
            ],
            "providers": [],
        },
    )

    result = billing_routes.get_spending_graph_status(period="day", group_by="model")

    chart = result["chart"]
    assert chart["title"] == "Model Spend by Model"
    assert chart["source_note"] == "Usage ledger estimates"
    assert chart["usage"]["source_label"] == "Usage ledger"
    assert chart["usage"]["events"] == 3
    assert chart["usage"]["total_tokens"] == 1500
    assert chart["usage"]["unknown_cost_events"] == 1
    assert chart["accounts"][0]["label"] == "gpt-4o"
    assert chart["accounts"][0]["source_label"] == "Usage estimate"
    assert chart["accounts"][0]["usage"]["input_tokens"] == 1000
    assert chart["accounts"][0]["usage"]["output_tokens"] == 250
    assert chart["accounts"][1]["usage"]["unknown_cost_events"] == 1


def test_cloud_monthly_spend_uses_success_cache(monkeypatch):
    calls = []
    monkeypatch.setattr(
        billing_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [_account()],
            "cloud_billing_refresh_seconds": 300,
            "cloud_billing_monthly_warning_usd": "",
        },
    )

    def fetch(token):
        calls.append(token)
        return {"month_to_date_usage": "1.00"}

    _set_digitalocean_fetch(monkeypatch, fetch)
    endpoint = _endpoint()

    first = endpoint(_request())
    second = endpoint(_request())

    assert first["cached"] is False
    assert second["cached"] is True
    assert calls == ["token"]


@pytest.mark.asyncio
async def test_manage_billing_tool_returns_chart_response(monkeypatch):
    from src.tool_implementations import do_manage_billing

    chart = {
        "version": 1,
        "kind": "billing-spend",
        "title": "Cloud Spend",
        "subtitle": "June 2026 month-to-date",
        "enabled": True,
        "configured": True,
        "total": 1.25,
        "total_display": "$1.25",
        "projected": 3.75,
        "projected_display": "$3.75",
        "accounts": [],
        "history": [],
    }
    monkeypatch.setattr(
        billing_routes,
        "get_spending_graph_status",
        lambda refresh=False, forced_provider=None, period="month", group_by="provider": {
            "amount": "1.25",
            "chart": chart,
            "markdown": billing_routes.billing_chart_markdown(chart),
        },
    )

    result = await do_manage_billing(json.dumps({"action": "spending_graph", "refresh": True}))

    assert result["exit_code"] == 0
    assert "```billing-chart" in result["response"]
    assert "Current total: $1.25" in result["response"]


def test_billing_graph_request_is_classified_as_billing_intent():
    from src.action_intents import classify_tool_intent, message_needs_tools

    slash_billing = classify_tool_intent("/billing")
    today_by_model = classify_tool_intent("/billing today by model")
    billing_usage_by_model = classify_tool_intent("show billing usage by model")
    spend_graph = classify_tool_intent("show me a spending graph")
    monthly_spend = classify_tool_intent("what is my current monthly spend?")
    calendar = classify_tool_intent("show me my calendar")

    assert slash_billing is not None
    assert slash_billing.kind == "direct_tool"
    assert slash_billing.tool == "manage_billing"
    assert slash_billing.args == {"action": "spending_graph", "refresh": True}
    assert today_by_model.args["period"] == "day"
    assert today_by_model.args["group_by"] == "model"
    assert billing_usage_by_model is not None
    assert billing_usage_by_model.args["group_by"] == "model"
    assert message_needs_tools("show me a spending graph")
    assert spend_graph is not None
    assert spend_graph.kind == "direct_tool"
    assert monthly_spend is not None
    assert monthly_spend.kind == "direct_tool"
    assert calendar is not None
    assert calendar.kind == "agent_tool"


def test_manage_billing_function_call_converts_to_tool_block():
    from src.tool_schemas import function_call_to_tool_block

    block = function_call_to_tool_block("manage_billing", json.dumps({"action": "graph"}))

    assert block is not None
    assert block.tool_type == "manage_billing"
    assert json.loads(block.content)["action"] == "graph"


def test_cloud_spend_limit_blocks_remote_model_urls(monkeypatch):
    from src import llm_core

    monkeypatch.setattr(
        billing_routes,
        "get_monthly_spend_status",
        lambda refresh=False, forced_provider=None: {
            "limit_usd": "1.00",
            "over_limit": True,
            "display": "$1.25",
        },
    )

    reason = llm_core._cloud_spend_limit_error("https://inference.do-ai.run/v1/chat/completions")

    assert "Cloud spend limit reached" in reason
    assert llm_core._cloud_spend_limit_error("http://127.0.0.1:11434/v1/chat/completions") is None


def test_cloud_spend_limit_blocks_sync_model_call_before_network(monkeypatch):
    from src import llm_core

    calls = []
    llm_core._response_cache.clear()
    monkeypatch.setattr(
        billing_routes,
        "get_monthly_spend_status",
        lambda refresh=False, forced_provider=None: {
            "limit_usd": "1.00",
            "over_limit": True,
            "display": "$1.25",
        },
    )
    monkeypatch.setattr(llm_core.httpx, "post", lambda *args, **kwargs: calls.append(args))

    with pytest.raises(HTTPException) as exc:
        llm_core.llm_call(
            "https://inference.do-ai.run/v1/chat/completions",
            "remote-model",
            [{"role": "user", "content": "hello"}],
        )

    assert exc.value.status_code == 402
    assert "Cloud spend limit reached" in exc.value.detail
    assert calls == []


@pytest.mark.asyncio
async def test_cloud_spend_limit_blocks_async_model_call_before_network(monkeypatch):
    from src import llm_core

    llm_core._response_cache.clear()
    monkeypatch.setattr(
        billing_routes,
        "get_monthly_spend_status",
        lambda refresh=False, forced_provider=None: {
            "limit_usd": "1.00",
            "over_limit": True,
            "display": "$1.25",
        },
    )

    with pytest.raises(HTTPException) as exc:
        await llm_core.llm_call_async(
            "https://inference.do-ai.run/v1/chat/completions",
            "remote-model",
            [{"role": "user", "content": "hello"}],
            max_retries=1,
        )

    assert exc.value.status_code == 402
    assert "Cloud spend limit reached" in exc.value.detail


@pytest.mark.asyncio
async def test_cloud_spend_limit_blocks_streaming_model_call(monkeypatch):
    from src import llm_core

    monkeypatch.setattr(
        billing_routes,
        "get_monthly_spend_status",
        lambda refresh=False, forced_provider=None: {
            "limit_usd": "1.00",
            "over_limit": True,
            "display": "$1.25",
        },
    )

    chunks = [
        chunk
        async for chunk in llm_core.stream_llm(
            "https://inference.do-ai.run/v1/chat/completions",
            "remote-model",
            [{"role": "user", "content": "hello"}],
        )
    ]

    assert len(chunks) == 1
    assert chunks[0].startswith("event: error")
    payload = json.loads(chunks[0].split("data: ", 1)[1])
    assert payload["status"] == 402
    assert "Cloud spend limit reached" in payload["error"]


@pytest.mark.asyncio
async def test_cloud_spend_limit_can_fall_back_to_local_model(monkeypatch):
    from src import llm_core

    calls = []
    llm_core._response_cache.clear()
    monkeypatch.setattr(
        billing_routes,
        "get_monthly_spend_status",
        lambda refresh=False, forced_provider=None: {
            "limit_usd": "1.00",
            "over_limit": True,
            "display": "$1.25",
        },
    )

    class _Response:
        is_success = True
        status_code = 200
        text = ""

        def json(self):
            return {"choices": [{"message": {"content": "local ok"}}]}

    class _Client:
        async def post(self, url, **kwargs):
            calls.append(url)
            return _Response()

    monkeypatch.setattr(llm_core, "_get_http_client", lambda: _Client())

    result = await llm_core.llm_call_async_with_fallback(
        [
            ("https://inference.do-ai.run/v1/chat/completions", "remote-model", {}),
            ("http://127.0.0.1:7009/v1/chat/completions", "local-model", {}),
        ],
        [{"role": "user", "content": "hello"}],
        max_retries=1,
    )

    assert result == "local ok"
    assert calls == ["http://127.0.0.1:7009/v1/chat/completions"]


class _AuthRoutesManager:
    is_configured = True
    signup_enabled = False

    def get_username_for_token(self, token):
        return "admin" if token == "session" else None

    def is_admin(self, user):
        return user == "admin"


class _JsonRequest:
    cookies = {"odysseus_session": "session"}

    def __init__(self, body=None):
        self._body = body or {}

    async def json(self):
        return self._body


def _auth_settings_endpoint(method):
    router = auth_routes.setup_auth_routes(_AuthRoutesManager())
    for route in router.routes:
        if getattr(route, "path", "") != "/api/auth/settings":
            continue
        methods = getattr(route, "methods", set())
        if method in methods:
            return route.endpoint
    raise AssertionError(f"{method} /api/auth/settings route not found")


@pytest.mark.asyncio
async def test_auth_settings_does_not_return_cloud_billing_token_to_admin(monkeypatch):
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(
        auth_routes,
        "_load_settings",
        lambda: {"cloud_billing_accounts": [_account(token="enc:stored-token")]},
    )

    result = await _auth_settings_endpoint("GET")(_JsonRequest())

    assert result["cloud_billing_accounts"][0]["api_token"] == ""
    assert result["cloud_billing_accounts"][0]["api_token_set"] is True


@pytest.mark.asyncio
async def test_auth_settings_encrypts_and_scrubs_cloud_billing_token_on_save(monkeypatch):
    saved = {}
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(auth_routes, "_load_settings", lambda: {})
    monkeypatch.setattr(auth_routes, "_save_settings", lambda settings: saved.update(settings))

    import src.secret_storage as secret_storage

    monkeypatch.setattr(secret_storage, "encrypt", lambda value: f"enc:{value}")

    result = await _auth_settings_endpoint("POST")(
        _JsonRequest({"cloud_billing_accounts": [_account(token="plain-token")]})
    )

    assert saved["cloud_billing_accounts"][0]["api_token"] == "enc:plain-token"
    assert result["cloud_billing_accounts"][0]["api_token"] == ""
    assert result["cloud_billing_accounts"][0]["api_token_set"] is True


@pytest.mark.asyncio
async def test_auth_settings_preserves_cloud_billing_token_on_save_without_new_token(monkeypatch):
    saved = {}
    monkeypatch.setattr(auth_routes, "migrate_from_settings", lambda: None)
    monkeypatch.setattr(
        auth_routes,
        "_load_settings",
        lambda: {
            "cloud_billing_enabled": True,
            "cloud_billing_accounts": [_account(account_id="do-main", token="enc:stored-token")],
            "cloud_billing_monthly_limit_usd": "",
        },
    )
    monkeypatch.setattr(auth_routes, "_save_settings", lambda settings: saved.update(settings))

    result = await _auth_settings_endpoint("POST")(
        _JsonRequest(
            {
                "cloud_billing_enabled": True,
                "cloud_billing_accounts": [
                    {
                        "id": "do-main",
                        "provider": "digitalocean",
                        "label": "Main",
                        "enabled": True,
                    }
                ],
                "cloud_billing_monthly_limit_usd": "1.00",
            }
        )
    )

    assert saved["cloud_billing_accounts"][0]["api_token"] == "enc:stored-token"
    assert saved["cloud_billing_monthly_limit_usd"] == "1.00"
    assert result["cloud_billing_accounts"][0]["api_token"] == ""
    assert result["cloud_billing_accounts"][0]["api_token_set"] is True
