"""Address geocoding helpers for Daily Logbook places."""

from __future__ import annotations

import asyncio
import json
import math
import os
import time
import uuid
from typing import Callable, Optional
from urllib.parse import urlparse

import httpx
from fastapi import HTTPException

from core.database import LogbookGeocodeCache, SessionLocal as _SessionLocal, utcnow_naive


_NOMINATIM_PUBLIC_URL = "https://nominatim.openstreetmap.org"
_GEOCODER_RATE_LOCK = asyncio.Lock()
_GEOCODER_LAST_REQUEST_AT = 0.0


def configured_geocoder() -> tuple[str, str]:
    provider = (os.getenv("LOGBOOK_GEOCODER_PROVIDER") or "photon").strip().lower()
    if provider in {"nominatim_public", "public_nominatim", "nominatim-osm"}:
        provider = "nominatim"
    if provider not in {"photon", "nominatim"}:
        raise HTTPException(400, "Unsupported logbook geocoder provider")
    base_url = (os.getenv("LOGBOOK_GEOCODER_URL") or "").strip().rstrip("/")
    if provider == "nominatim" and not base_url:
        base_url = _NOMINATIM_PUBLIC_URL
    if not base_url:
        raise HTTPException(503, "Local logbook geocoder is not configured")
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise HTTPException(503, "Local logbook geocoder URL is invalid")
    return provider, base_url


def geocode_query_key(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def geocode_cache_get(
    provider: str,
    query_key: str,
    *,
    session_factory: Callable = _SessionLocal,
) -> Optional[list]:
    db = session_factory()
    try:
        row = db.query(LogbookGeocodeCache).filter(
            LogbookGeocodeCache.provider == provider,
            LogbookGeocodeCache.query_key == query_key,
        ).first()
        if not row:
            return None
        data = json.loads(row.result_json or "[]")
        return data if isinstance(data, list) else None
    except Exception:
        return None
    finally:
        db.close()


def geocode_cache_set(
    provider: str,
    query: str,
    query_key: str,
    results: list,
    *,
    session_factory: Callable = _SessionLocal,
) -> None:
    db = session_factory()
    try:
        now = utcnow_naive()
        payload = json.dumps(results, ensure_ascii=False)
        row = db.query(LogbookGeocodeCache).filter(
            LogbookGeocodeCache.provider == provider,
            LogbookGeocodeCache.query_key == query_key,
        ).first()
        if row:
            row.query = query
            row.result_json = payload
            row.updated_at = now
        else:
            db.add(LogbookGeocodeCache(
                id=str(uuid.uuid4()),
                provider=provider,
                query=query,
                query_key=query_key,
                result_json=payload,
                created_at=now,
                updated_at=now,
            ))
        db.commit()
    except Exception:
        db.rollback()
    finally:
        db.close()


async def respect_public_geocoder_rate_limit(provider: str, base_url: str) -> None:
    global _GEOCODER_LAST_REQUEST_AT
    if provider != "nominatim" or urlparse(base_url).netloc.lower() != "nominatim.openstreetmap.org":
        return
    async with _GEOCODER_RATE_LOCK:
        elapsed = time.monotonic() - _GEOCODER_LAST_REQUEST_AT
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _GEOCODER_LAST_REQUEST_AT = time.monotonic()


def geocoder_user_agent() -> str:
    return (
        os.getenv("LOGBOOK_GEOCODER_USER_AGENT")
        or "OdysseusLogbook/1.0 (self-hosted; https://github.com/pewdiepie-archdaemon/odysseus)"
    ).strip()


def _photon_prop(properties: dict, *names: str) -> str:
    for name in names:
        value = properties.get(name)
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def photon_feature_to_candidate(feature: dict) -> Optional[dict]:
    geometry = feature.get("geometry") if isinstance(feature, dict) else {}
    coordinates = geometry.get("coordinates") if isinstance(geometry, dict) else None
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    try:
        longitude = float(coordinates[0])
        latitude = float(coordinates[1])
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None

    properties = feature.get("properties") if isinstance(feature, dict) else {}
    if not isinstance(properties, dict):
        properties = {}
    name = _photon_prop(properties, "name", "street", "city", "country")
    street = _photon_prop(properties, "street")
    house_number = _photon_prop(properties, "housenumber")
    street_line = " ".join(part for part in [street, house_number] if part)
    address_parts = [
        street_line,
        _photon_prop(properties, "postcode"),
        _photon_prop(properties, "city", "county"),
        _photon_prop(properties, "state"),
        _photon_prop(properties, "country"),
    ]
    address = ", ".join(dict.fromkeys(part for part in address_parts if part))
    label = name or address or "Map result"
    osm_type = _photon_prop(properties, "osm_type")
    osm_id = _photon_prop(properties, "osm_id")
    osm_key = _photon_prop(properties, "osm_key")
    osm_value = _photon_prop(properties, "osm_value")
    return {
        "provider": "photon",
        "provider_id": ":".join(part for part in [osm_type, osm_id] if part) or None,
        "label": label,
        "address": address or label,
        "latitude": latitude,
        "longitude": longitude,
        "kind": "/".join(part for part in [osm_key, osm_value] if part) or None,
    }


def nominatim_result_to_candidate(item: dict) -> Optional[dict]:
    try:
        latitude = float(item.get("lat"))
        longitude = float(item.get("lon"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(latitude) or not math.isfinite(longitude):
        return None
    display_name = str(item.get("display_name") or "").strip()
    address = item.get("address") if isinstance(item.get("address"), dict) else {}
    label = (
        address.get("amenity")
        or address.get("shop")
        or address.get("building")
        or address.get("road")
        or address.get("city")
        or address.get("town")
        or address.get("village")
        or display_name
        or "Map result"
    )
    osm_type = str(item.get("osm_type") or "").strip()
    osm_id = str(item.get("osm_id") or "").strip()
    category = str(item.get("category") or "").strip()
    place_type = str(item.get("type") or "").strip()
    return {
        "provider": "nominatim",
        "provider_id": ":".join(part for part in [osm_type, osm_id] if part) or None,
        "label": str(label),
        "address": display_name or str(label),
        "latitude": latitude,
        "longitude": longitude,
        "kind": "/".join(part for part in [category, place_type] if part) or None,
    }


async def geocode_address(
    query: str,
    limit: int = 5,
    *,
    session_factory: Callable = _SessionLocal,
) -> dict:
    query = (query or "").strip()
    if len(query) < 3:
        raise HTTPException(400, "Enter at least 3 characters to geocode")
    limit = max(1, min(int(limit or 5), 10))
    provider, base_url = configured_geocoder()
    query_key = geocode_query_key(query)
    cached = geocode_cache_get(provider, query_key, session_factory=session_factory)
    if cached is not None:
        return {"ok": True, "provider": provider, "query": query, "results": cached, "cached": True}

    try:
        timeout = httpx.Timeout(connect=1.5, read=6.0, write=2.0, pool=2.0)
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=False, trust_env=False) as client:
            if provider == "photon":
                url = f"{base_url}/api"
                params = {"q": query, "limit": limit}
                headers = None
            else:
                await respect_public_geocoder_rate_limit(provider, base_url)
                url = f"{base_url}/search"
                params = {
                    "q": query,
                    "format": "jsonv2",
                    "addressdetails": "1",
                    "limit": limit,
                }
                email = (os.getenv("LOGBOOK_GEOCODER_EMAIL") or "").strip()
                if email:
                    params["email"] = email
                headers = {"User-Agent": geocoder_user_agent()}
            response = await client.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except httpx.TimeoutException:
        raise HTTPException(504, "Logbook geocoder timed out")
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code if exc.response is not None else "unknown"
        raise HTTPException(502, f"Logbook geocoder returned {status}")
    except httpx.RequestError:
        raise HTTPException(503, "Logbook geocoder is unavailable")
    except ValueError:
        raise HTTPException(502, "Logbook geocoder returned invalid JSON")

    if provider == "photon":
        features = payload.get("features") if isinstance(payload, dict) else []
        if not isinstance(features, list):
            features = []
        results = [
            candidate
            for feature in features[:limit] if isinstance(feature, dict)
            if (candidate := photon_feature_to_candidate(feature))
        ]
    else:
        rows = payload if isinstance(payload, list) else []
        results = [
            candidate
            for item in rows[:limit] if isinstance(item, dict)
            if (candidate := nominatim_result_to_candidate(item))
        ]
    geocode_cache_set(provider, query, query_key, results, session_factory=session_factory)
    return {"ok": True, "provider": provider, "query": query, "results": results, "cached": False}
