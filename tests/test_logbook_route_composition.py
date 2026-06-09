from routes.logbook_routes import setup_logbook_routes


def _route_methods(router):
    methods = {}
    for route in router.routes:
        if hasattr(route, "path"):
            methods.setdefault(route.path, set()).update(route.methods or set())
    return methods


def test_logbook_router_composes_ai_routes_with_existing_prefix():
    methods = _route_methods(setup_logbook_routes())

    assert "GET" in methods["/api/logbook/ai/status"]
    assert "POST" in methods["/api/logbook/ai/estimate"]
    assert "GET" in methods["/api/logbook/ai/usage-summary"]
    assert "POST" in methods["/api/logbook/ai/assist"]
    assert "POST" in methods["/api/logbook/ai/analyze-entry/{entry_id}"]


def test_logbook_router_keeps_core_custom_routes_composed():
    methods = _route_methods(setup_logbook_routes())

    assert "GET" in methods["/api/logbook/atlas"]
    assert "GET" in methods["/api/logbook/geocode"]
    assert "GET" in methods["/api/logbook/people"]
    assert "GET" in methods["/api/logbook/locations"]
    assert "GET" in methods["/api/logbook/connections"]
