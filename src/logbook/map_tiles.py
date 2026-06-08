"""Optional Logbook map tile configuration."""

from __future__ import annotations

import os
from urllib.parse import urlparse


_DISABLED_PROVIDERS = {"", "0", "false", "local", "none", "off"}
_ESRI_WORLD_IMAGERY_URL = (
    "https://server.arcgisonline.com/ArcGIS/rest/services/"
    "World_Imagery/MapServer/tile/{z}/{y}/{x}"
)

_TILE_PRESETS = {
    "satellite": (
        "esri_world_imagery",
        _ESRI_WORLD_IMAGERY_URL,
        "Tiles (c) Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    ),
    "esri": (
        "esri_world_imagery",
        _ESRI_WORLD_IMAGERY_URL,
        "Tiles (c) Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    ),
    "esri_world_imagery": (
        "esri_world_imagery",
        _ESRI_WORLD_IMAGERY_URL,
        "Tiles (c) Esri, Maxar, Earthstar Geographics, and the GIS User Community",
    ),
}


def _max_zoom() -> int:
    try:
        value = int(os.getenv("LOGBOOK_MAP_TILE_MAX_ZOOM") or "18")
    except ValueError:
        value = 18
    return max(1, min(value, 20))


def _disabled_config(provider: str = "local", error: str = "") -> dict:
    payload = {
        "tiles_enabled": False,
        "provider": provider or "local",
        "tile_url": "",
        "attribution": "",
        "max_zoom": _max_zoom(),
    }
    if error:
        payload["error"] = error
    return payload


def _url_origin(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    if parsed.username or parsed.password:
        return ""
    try:
        port = parsed.port
    except ValueError:
        return ""
    host = parsed.hostname or ""
    if not host or ";" in host or any(ch.isspace() for ch in host):
        return ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{parsed.scheme}://{host}{f':{port}' if port else ''}"


def map_tile_config() -> dict:
    """Return browser-safe map tile configuration for the Logbook atlas.

    Tile URLs are public browser URLs by design. Do not put private server-only
    secrets in LOGBOOK_MAP_TILE_URL.
    """

    raw_provider = (os.getenv("LOGBOOK_MAP_TILE_PROVIDER") or "").strip().lower()
    raw_url = (os.getenv("LOGBOOK_MAP_TILE_URL") or "").strip()
    max_zoom = _max_zoom()

    if not raw_url and raw_provider in _DISABLED_PROVIDERS:
        return _disabled_config(raw_provider or "local")

    attribution = (os.getenv("LOGBOOK_MAP_TILE_ATTRIBUTION") or "").strip()
    if raw_url:
        provider = raw_provider or "custom"
        tile_url = raw_url
    else:
        preset = _TILE_PRESETS.get(raw_provider)
        if not preset:
            return _disabled_config(raw_provider, "Unsupported logbook map tile provider")
        provider, tile_url, default_attribution = preset
        attribution = attribution or default_attribution

    if not _url_origin(tile_url):
        return _disabled_config(provider, "Logbook map tile URL must be http(s)")
    missing = [token for token in ("{z}", "{x}", "{y}") if token not in tile_url]
    if missing:
        return _disabled_config(provider, "Logbook map tile URL must include {z}, {x}, and {y}")

    return {
        "tiles_enabled": True,
        "provider": provider,
        "tile_url": tile_url,
        "attribution": attribution,
        "max_zoom": max_zoom,
    }


def map_tile_csp_origin() -> str:
    config = map_tile_config()
    if not config.get("tiles_enabled"):
        return ""
    return _url_origin(str(config.get("tile_url") or ""))
