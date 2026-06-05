from types import SimpleNamespace

import pytest
from fastapi import HTTPException

import routes.session_routes as session_routes
import src.event_bus as event_bus
import src.llm_core as llm_core


def _route(router, path: str, method: str):
    method = method.upper()
    for route in reversed(router.routes):
        if getattr(route, "path", "") == path and method in getattr(route, "methods", set()):
            return route.endpoint
    raise AssertionError(f"route not found: {method} {path}")


class _SessionManager:
    def __init__(self):
        self.created = []

    def create_session(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(name=kwargs["name"], headers={})


def _request():
    return SimpleNamespace(state=SimpleNamespace())


def _patch_auth(monkeypatch):
    monkeypatch.setattr(session_routes, "get_current_user", lambda request: None)
    monkeypatch.setattr(session_routes, "effective_user", lambda request: None)


def test_create_session_without_model_rejects_all_non_chat_models(monkeypatch):
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        llm_core,
        "list_model_ids",
        lambda *args, **kwargs: ["openai-gpt-5.4-pro", "qwen3-embedding-0.6b"],
    )
    manager = _SessionManager()
    target = _route(session_routes.setup_session_routes(manager, {}), "/api/session", "POST")

    with pytest.raises(HTTPException) as exc:
        target(
            _request(),
            name="",
            endpoint_url="https://inference.do-ai.run/v1/chat/completions",
            model="",
            rag="false",
            skip_validation="false",
            api_key="",
            endpoint_id="",
        )

    assert exc.value.status_code == 400
    assert exc.value.detail == "No chat-capable models found at server"
    assert manager.created == []


def test_create_session_without_model_picks_first_chat_model(monkeypatch):
    _patch_auth(monkeypatch)
    monkeypatch.setattr(
        llm_core,
        "list_model_ids",
        lambda *args, **kwargs: [
            "openai-gpt-5.4-pro",
            "qwen3-embedding-0.6b",
            "deepseek-4-flash",
        ],
    )
    monkeypatch.setattr(event_bus, "fire_event", lambda *args, **kwargs: None)
    manager = _SessionManager()
    target = _route(session_routes.setup_session_routes(manager, {}), "/api/session", "POST")

    result = target(
        _request(),
        name="Chat",
        endpoint_url="https://inference.do-ai.run/v1/chat/completions",
        model="",
        rag="false",
        skip_validation="false",
        api_key="",
        endpoint_id="",
    )

    assert result.model == "deepseek-4-flash"
    assert manager.created[0]["model"] == "deepseek-4-flash"
