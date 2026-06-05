import sys
import types
from pathlib import Path

from fastapi import APIRouter, FastAPI, Request
from fastapi.responses import HTMLResponse

from custom.bootstrap import register_custom_features


def _dummy_router(path: str) -> APIRouter:
    router = APIRouter()

    @router.get(path)
    def endpoint():
        return {"ok": True}

    return router


def test_register_custom_features_mounts_custom_routers_and_pages(monkeypatch):
    billing_routes = types.ModuleType("routes.billing_routes")
    billing_routes.setup_billing_routes = lambda: _dummy_router("/api/billing-test")

    logbook_routes = types.ModuleType("routes.logbook_routes")
    logbook_routes.setup_logbook_routes = lambda: _dummy_router("/api/logbook-test")

    monkeypatch.setitem(sys.modules, "routes.billing_routes", billing_routes)
    monkeypatch.setitem(sys.modules, "routes.logbook_routes", logbook_routes)

    app = FastAPI()

    async def serve_index(request: Request):
        return HTMLResponse("spa")

    register_custom_features(app, serve_index)

    paths = {getattr(route, "path", "") for route in app.routes}
    assert "/api/billing-test" in paths
    assert "/api/logbook-test" in paths
    assert "/logbook" in paths
    assert "/logbook/atlas" in paths


def test_app_uses_single_custom_bootstrap_hook():
    source = (Path(__file__).resolve().parents[1] / "app.py").read_text(encoding="utf-8")

    assert "from custom.bootstrap import register_custom_features" in source
    assert "register_custom_features(app, serve_index)" in source
    assert "from routes.billing_routes import setup_billing_routes" not in source
    assert "from routes.logbook_routes import setup_logbook_routes" not in source
