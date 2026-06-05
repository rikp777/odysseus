"""Custom branch FastAPI wiring.

Keep personal-feature route registration out of the upstream-owned app module.
The main app should call only `register_custom_features(...)`.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from fastapi import Request
from fastapi.responses import HTMLResponse


ServeIndex = Callable[[Request], Awaitable[HTMLResponse]]


def register_custom_features(app, serve_index: ServeIndex) -> None:
    """Register custom branch routers and SPA pages."""
    from routes.billing_routes import setup_billing_routes
    from routes.logbook_routes import setup_logbook_routes

    app.include_router(setup_billing_routes())
    app.include_router(setup_logbook_routes())

    @app.get("/logbook")
    async def serve_logbook(request: Request):
        return await serve_index(request)

    @app.get("/logbook/atlas")
    async def serve_logbook_atlas(request: Request):
        return await serve_index(request)
