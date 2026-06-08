from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base
from routes import logbook_routes


class _FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        return None


class _FakeAsyncClient:
    calls = []
    payload = None

    def __init__(self, **kwargs):
        self.kwargs = kwargs

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, params=None, headers=None):
        self.calls.append({"url": url, "params": params, "headers": headers, "kwargs": self.kwargs})
        return _FakeResponse(self.payload or {
            "features": [{
                "geometry": {"coordinates": [4.9001, 52.3712]},
                "properties": {
                    "name": "Central Library",
                    "street": "Main Street",
                    "housenumber": "12",
                    "postcode": "1000 AA",
                    "city": "Example City",
                    "country": "Netherlands",
                    "osm_type": "N",
                    "osm_id": "123",
                    "osm_key": "amenity",
                    "osm_value": "library",
                },
            }],
})


def _client(monkeypatch, tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'logbook-geocoder.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(logbook_routes, "SessionLocal", TestingSessionLocal)
    monkeypatch.setattr(logbook_routes, "require_user", lambda request: None)
    monkeypatch.setattr(logbook_routes, "effective_user", lambda request: "owner-1")
    app = FastAPI()
    app.include_router(logbook_routes.setup_logbook_routes())
    return TestClient(app)


def test_logbook_geocode_uses_configured_photon_endpoint(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGBOOK_GEOCODER_URL", "http://geocoder:2322/")
    monkeypatch.setenv("LOGBOOK_GEOCODER_PROVIDER", "photon")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.payload = None
    monkeypatch.setattr(logbook_routes.httpx, "AsyncClient", _FakeAsyncClient)

    response = _client(monkeypatch, tmp_path).get("/api/logbook/geocode", params={"q": "Main Street 12", "limit": 3})

    assert response.status_code == 200
    payload = response.json()
    assert payload["provider"] == "photon"
    assert payload["results"] == [{
        "provider": "photon",
        "provider_id": "N:123",
        "label": "Central Library",
        "address": "Main Street 12, 1000 AA, Example City, Netherlands",
        "latitude": 52.3712,
        "longitude": 4.9001,
        "kind": "amenity/library",
    }]
    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"] == "http://geocoder:2322/api"
    assert call["params"] == {"q": "Main Street 12", "limit": 3}
    assert call["headers"] is None
    assert call["kwargs"]["follow_redirects"] is False
    assert call["kwargs"]["trust_env"] is False


def test_logbook_geocode_requires_local_geocoder_config(monkeypatch, tmp_path):
    monkeypatch.delenv("LOGBOOK_GEOCODER_URL", raising=False)
    monkeypatch.delenv("LOGBOOK_GEOCODER_PROVIDER", raising=False)

    response = _client(monkeypatch, tmp_path).get("/api/logbook/geocode", params={"q": "Main Street 12"})

    assert response.status_code == 503
    assert "not configured" in response.json()["detail"]


def test_logbook_geocode_supports_public_nominatim_with_user_agent_and_cache(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGBOOK_GEOCODER_PROVIDER", "nominatim")
    monkeypatch.setenv("LOGBOOK_GEOCODER_USER_AGENT", "OdysseusTest/1.0 (tests)")
    monkeypatch.setenv("LOGBOOK_GEOCODER_EMAIL", "dev@example.test")
    _FakeAsyncClient.calls = []
    _FakeAsyncClient.payload = [{
        "osm_type": "way",
        "osm_id": 456,
        "lat": "52.3712",
        "lon": "4.9001",
        "display_name": "Main Street 12, Example City, Netherlands",
        "category": "building",
        "type": "yes",
        "address": {"road": "Main Street", "house_number": "12", "city": "Example City"},
    }]
    monkeypatch.setattr(logbook_routes.httpx, "AsyncClient", _FakeAsyncClient)

    client = _client(monkeypatch, tmp_path)
    first = client.get("/api/logbook/geocode", params={"q": "Main Street 12", "limit": 2})
    second = client.get("/api/logbook/geocode", params={"q": " main  street 12 ", "limit": 2})

    assert first.status_code == 200
    assert second.status_code == 200
    assert first.json()["provider"] == "nominatim"
    assert first.json()["results"] == [{
        "provider": "nominatim",
        "provider_id": "way:456",
        "label": "Main Street",
        "address": "Main Street 12, Example City, Netherlands",
        "latitude": 52.3712,
        "longitude": 4.9001,
        "kind": "building/yes",
    }]
    assert second.json()["cached"] is True
    assert len(_FakeAsyncClient.calls) == 1
    call = _FakeAsyncClient.calls[0]
    assert call["url"] == "https://nominatim.openstreetmap.org/search"
    assert call["params"] == {
        "q": "Main Street 12",
        "format": "jsonv2",
        "addressdetails": "1",
        "limit": 2,
        "email": "dev@example.test",
    }
    assert call["headers"] == {"User-Agent": "OdysseusTest/1.0 (tests)"}


def test_logbook_map_config_defaults_to_private_local_grid(monkeypatch, tmp_path):
    monkeypatch.delenv("LOGBOOK_MAP_TILE_PROVIDER", raising=False)
    monkeypatch.delenv("LOGBOOK_MAP_TILE_URL", raising=False)
    monkeypatch.delenv("LOGBOOK_MAP_TILE_ATTRIBUTION", raising=False)
    monkeypatch.delenv("LOGBOOK_MAP_TILE_MAX_ZOOM", raising=False)

    response = _client(monkeypatch, tmp_path).get("/api/logbook/map/config")

    assert response.status_code == 200
    assert response.json() == {
        "tiles_enabled": False,
        "provider": "local",
        "tile_url": "",
        "attribution": "",
        "max_zoom": 18,
    }


def test_logbook_map_config_supports_satellite_preset(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGBOOK_MAP_TILE_PROVIDER", "satellite")
    monkeypatch.delenv("LOGBOOK_MAP_TILE_URL", raising=False)
    monkeypatch.delenv("LOGBOOK_MAP_TILE_ATTRIBUTION", raising=False)
    monkeypatch.delenv("LOGBOOK_MAP_TILE_MAX_ZOOM", raising=False)

    response = _client(monkeypatch, tmp_path).get("/api/logbook/map/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tiles_enabled"] is True
    assert payload["provider"] == "esri_world_imagery"
    assert payload["tile_url"] == (
        "https://server.arcgisonline.com/ArcGIS/rest/services/"
        "World_Imagery/MapServer/tile/{z}/{y}/{x}"
    )
    assert "{z}" in payload["tile_url"]
    assert "{x}" in payload["tile_url"]
    assert "{y}" in payload["tile_url"]
    assert "Esri" in payload["attribution"]


def test_logbook_map_config_rejects_invalid_custom_template(monkeypatch, tmp_path):
    monkeypatch.setenv("LOGBOOK_MAP_TILE_PROVIDER", "custom")
    monkeypatch.setenv("LOGBOOK_MAP_TILE_URL", "https://tiles.example.test/{z}/{x}.png")

    response = _client(monkeypatch, tmp_path).get("/api/logbook/map/config")

    assert response.status_code == 200
    payload = response.json()
    assert payload["tiles_enabled"] is False
    assert "must include" in payload["error"]
