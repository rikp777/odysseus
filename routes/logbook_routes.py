"""Daily Logbook API."""

import asyncio
import json
import math
import os
import time
import uuid
from typing import Optional
from urllib.parse import urlparse

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from core.database import (
    LogbookDataPoint,
    LogbookEntry,
    LogbookGeocodeCache,
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
    LogbookPerson,
    LogbookPersonConnection,
    SessionLocal,
    utcnow_naive,
)
from src.auth_helpers import effective_user, require_user
from src.contacts import service as contacts_service
from src.logbook import ai as logbook_ai
from src.logbook.map_tiles import map_tile_config
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from src.tool_security import owner_is_admin_or_single_user
from src.logbook.schemas import (
    LogbookApplySuggestions,
    LogbookAIAssist,
    LogbookConnectionCreate,
    LogbookConnectionUpdate,
    LogbookEntryUpdate,
    LogbookEntryUpsert,
    LogbookLocationCreate,
    LogbookLocationsMerge,
    LogbookLocationUpdate,
    LogbookPeopleMerge,
    LogbookPersonContactLink,
    LogbookPersonCreate,
    LogbookPersonFactCreate,
    LogbookPersonUpdate,
)

_NOMINATIM_PUBLIC_URL = "https://nominatim.openstreetmap.org"
_GEOCODER_RATE_LOCK = asyncio.Lock()
_GEOCODER_LAST_REQUEST_AT = 0.0


def _owner(request: Request) -> str:
    require_user(request)
    return effective_user(request) or ""


def _clean_optional(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _configured_geocoder() -> tuple[str, str]:
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


def _geocode_query_key(query: str) -> str:
    return " ".join(str(query or "").strip().lower().split())


def _geocode_cache_get(provider: str, query_key: str) -> Optional[list]:
    db = SessionLocal()
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


def _geocode_cache_set(provider: str, query: str, query_key: str, results: list) -> None:
    db = SessionLocal()
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


async def _respect_public_geocoder_rate_limit(provider: str, base_url: str) -> None:
    global _GEOCODER_LAST_REQUEST_AT
    if provider != "nominatim" or urlparse(base_url).netloc.lower() != "nominatim.openstreetmap.org":
        return
    async with _GEOCODER_RATE_LOCK:
        elapsed = time.monotonic() - _GEOCODER_LAST_REQUEST_AT
        if elapsed < 1.0:
            await asyncio.sleep(1.0 - elapsed)
        _GEOCODER_LAST_REQUEST_AT = time.monotonic()


def _geocoder_user_agent() -> str:
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


def _photon_feature_to_candidate(feature: dict) -> Optional[dict]:
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


def _nominatim_result_to_candidate(item: dict) -> Optional[dict]:
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


def _contacts_allowed(owner: str) -> bool:
    try:
        return owner_is_admin_or_single_user(owner or None)
    except Exception:
        return not bool(owner)


def _contact_to_candidate(contact: dict) -> dict:
    return {
        "uid": str(contact.get("uid") or ""),
        "name": contact.get("name") or "",
        "emails": contact.get("emails") or [],
        "phones": contact.get("phones") or [],
        "source": "contacts",
    }


def _load_contact_or_404(owner: str, contact_uid: str) -> dict:
    if not _contacts_allowed(owner):
        raise HTTPException(403, "Contacts are not available for this user")
    uid = str(contact_uid or "").strip()
    if not uid:
        raise HTTPException(400, "contact_uid is required")
    for contact in contacts_service.fetch_contacts(force=True):
        if str(contact.get("uid") or "") == uid:
            return contact
    raise HTTPException(404, "Contact not found")


def _apply_contact_link(person: LogbookPerson, contact: dict) -> None:
    person.contact_uid = str(contact.get("uid") or "") or None
    person.contact_source = "contacts"
    person.contact_snapshot_json = json.dumps(_contact_to_candidate(contact), ensure_ascii=False)
    if not person.display_name and contact.get("name"):
        person.display_name = str(contact["name"]).strip()


def _clear_contact_link(person: LogbookPerson) -> None:
    person.contact_uid = None
    person.contact_source = None
    person.contact_snapshot_json = None


def _people_with_connection_summaries(db, owner: str, people, stats=None, *, limit_per_person: int = 4):
    stats = stats or logbook_repo.person_stats(db, owner)
    person_ids = [person.id for person in people]
    grouped = logbook_repo.connections_for_people(
        db,
        owner,
        person_ids,
        limit_per_person=limit_per_person,
    )
    facts_by_person = logbook_repo.person_facts_for_people(db, owner, person_ids, limit_per_person=3)
    rows = []
    for person in people:
        data = logbook_utils.with_stats(logbook_serializers.person_to_dict(person), stats.get(person.id, {}))
        summaries = [
            summary for conn in grouped.get(person.id, [])
            if (summary := logbook_serializers.connection_summary_to_dict(conn, person.id))
        ]
        data["connections_summary"] = summaries
        data["facts"] = [
            logbook_serializers.person_fact_to_dict(fact)
            for fact in facts_by_person.get(person.id, [])
        ]
        rows.append(data)
    return rows


def setup_logbook_routes() -> APIRouter:
    router = APIRouter(prefix="/api/logbook", tags=["logbook"])

    @router.get("/atlas")
    def atlas(request: Request, status: Optional[str] = None, include_hidden: bool = True):
        owner = _owner(request)
        db = SessionLocal()
        try:
            people = logbook_repo.person_query(db, owner).order_by(LogbookPerson.display_name.asc()).all()
            locations = logbook_repo.location_query(db, owner, include_hidden=include_hidden).order_by(LogbookLocation.display_name.asc()).all()
            person_stats = logbook_repo.person_stats(db, owner)
            location_stats = logbook_repo.location_stats(db, owner)
            conn_query = db.query(LogbookPersonConnection).options(
                selectinload(LogbookPersonConnection.person_a),
                selectinload(LogbookPersonConnection.person_b),
            ).filter(LogbookPersonConnection.owner == owner)
            if status:
                conn_query = conn_query.filter(LogbookPersonConnection.status == status)
            connections = conn_query.order_by(LogbookPersonConnection.updated_at.desc()).all()
            return {
                "people": _people_with_connection_summaries(db, owner, people, person_stats),
                "locations": [
                    logbook_utils.with_stats(logbook_serializers.location_to_dict(location), location_stats.get(location.id, {}))
                    for location in locations
                ],
                "connections": [logbook_serializers.connection_to_dict(conn) for conn in connections],
                "contacts_available": _contacts_allowed(owner),
            }
        finally:
            db.close()

    @router.get("/map")
    def map_locations(request: Request, with_coordinates: bool = False, include_hidden: bool = False):
        owner = _owner(request)
        db = SessionLocal()
        try:
            query = logbook_repo.location_query(db, owner, include_hidden=include_hidden)
            if with_coordinates:
                query = query.filter(LogbookLocation.latitude.isnot(None), LogbookLocation.longitude.isnot(None))
            locations = query.order_by(LogbookLocation.display_name.asc()).all()
            stats = logbook_repo.location_stats(db, owner)
            return {
                "locations": [
                    logbook_utils.with_stats(logbook_serializers.location_to_dict(location), stats.get(location.id, {}))
                    for location in locations
                ]
            }
        finally:
            db.close()

    @router.get("/map/config")
    def map_config(request: Request):
        _owner(request)
        return map_tile_config()

    @router.get("/geocode")
    async def geocode(request: Request, q: str, limit: int = 5):
        _owner(request)
        query = (q or "").strip()
        if len(query) < 3:
            raise HTTPException(400, "Enter at least 3 characters to geocode")
        limit = max(1, min(int(limit or 5), 10))
        provider, base_url = _configured_geocoder()
        query_key = _geocode_query_key(query)
        cached = _geocode_cache_get(provider, query_key)
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
                    await _respect_public_geocoder_rate_limit(provider, base_url)
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
                    headers = {"User-Agent": _geocoder_user_agent()}
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
                if (candidate := _photon_feature_to_candidate(feature))
            ]
        else:
            rows = payload if isinstance(payload, list) else []
            results = [
                candidate
                for item in rows[:limit] if isinstance(item, dict)
                if (candidate := _nominatim_result_to_candidate(item))
            ]
        _geocode_cache_set(provider, query, query_key, results)
        return {"ok": True, "provider": provider, "query": query, "results": results, "cached": False}

    @router.get("/entries")
    def list_entries(
        request: Request,
        start: Optional[str] = None,
        end: Optional[str] = None,
        q: Optional[str] = None,
        person_id: Optional[str] = None,
        location_id: Optional[str] = None,
        mood: Optional[str] = None,
        datapoint_key: Optional[str] = None,
    ):
        owner = _owner(request)
        if start:
            start = logbook_utils.validate_date(start)
        if end:
            end = logbook_utils.validate_date(end)
        db = SessionLocal()
        try:
            query = logbook_repo.entry_query(db, owner)
            if start:
                query = query.filter(LogbookEntry.entry_date >= start)
            if end:
                query = query.filter(LogbookEntry.entry_date <= end)
            if q:
                like = f"%{q.strip()}%"
                query = query.filter(or_(
                    LogbookEntry.title.ilike(like),
                    LogbookEntry.content.ilike(like),
                    LogbookEntry.summary.ilike(like),
                ))
            if mood:
                query = query.filter(LogbookEntry.mood_label == mood)
            if person_id:
                query = query.join(LogbookMention, LogbookMention.entry_id == LogbookEntry.id).filter(LogbookMention.person_id == person_id)
            if location_id:
                query = query.join(LogbookLocationMention, LogbookLocationMention.entry_id == LogbookEntry.id).filter(LogbookLocationMention.location_id == location_id)
            if datapoint_key:
                query = query.join(LogbookDataPoint, LogbookDataPoint.entry_id == LogbookEntry.id).filter(LogbookDataPoint.key == logbook_utils.clean_key(datapoint_key))
            if person_id or location_id or datapoint_key:
                query = query.distinct()
            entries = query.order_by(LogbookEntry.entry_date.desc(), LogbookEntry.updated_at.desc()).all()
            return {"entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries]}
        finally:
            db.close()

    @router.get("/entry/{entry_date}")
    def get_entry_by_date(request: Request, entry_date: str):
        owner = _owner(request)
        entry_date = logbook_utils.validate_date(entry_date)
        db = SessionLocal()
        try:
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.entry_date == entry_date).first()
            if not entry:
                return logbook_serializers.empty_entry_shape(entry_date)
            return logbook_serializers.entry_to_dict(entry)
        finally:
            db.close()

    @router.post("/entry/{entry_date}")
    def upsert_entry_by_date(request: Request, entry_date: str, body: LogbookEntryUpsert):
        owner = _owner(request)
        entry_date = logbook_utils.validate_date(entry_date)
        db = SessionLocal()
        try:
            entry = db.query(LogbookEntry).filter(
                LogbookEntry.owner == owner,
                LogbookEntry.entry_date == entry_date,
            ).first()
            revision_needed = entry is not None and logbook_repo.entry_will_change(entry, body)
            if not entry:
                entry = LogbookEntry(
                    id=str(uuid.uuid4()),
                    owner=owner,
                    entry_date=entry_date,
                    title=logbook_utils.normalized_title(body.title),
                    content=body.content or "",
                )
                db.add(entry)
                db.flush()
            elif revision_needed:
                logbook_repo.create_entry_revision(db, entry, source="manual_save")
            content_changed = logbook_repo.apply_entry_fields(entry, body)
            if body.datapoints is not None:
                logbook_repo.replace_datapoints(db, entry, body.datapoints)
            if content_changed or not entry.mentions or not entry.location_mentions:
                logbook_repo.rebuild_entry_links(db, owner, entry)
            if content_changed or body.datapoints is not None:
                logbook_repo.sync_linked_datapoints(db, entry)
            db.commit()
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.id == entry.id).first()
            return logbook_serializers.entry_to_dict(entry)
        except IntegrityError:
            db.rollback()
            raise HTTPException(409, "A logbook entry already exists for this date")
        finally:
            db.close()

    @router.put("/entry/{entry_id}")
    def update_entry(request: Request, entry_id: str, body: LogbookEntryUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            if logbook_repo.entry_will_change(entry, body):
                logbook_repo.create_entry_revision(db, entry, source="manual_save")
            content_changed = logbook_repo.apply_entry_fields(entry, body)
            if body.datapoints is not None:
                logbook_repo.replace_datapoints(db, entry, body.datapoints)
            if content_changed:
                logbook_repo.rebuild_entry_links(db, owner, entry)
            if content_changed or body.datapoints is not None:
                logbook_repo.sync_linked_datapoints(db, entry)
            db.commit()
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
            return logbook_serializers.entry_to_dict(entry)
        finally:
            db.close()

    @router.get("/entry/{entry_id}/revisions")
    def list_entry_revisions(request: Request, entry_id: str, limit: int = 20):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            revisions = logbook_repo.entry_revisions(db, owner, entry.id, limit=limit)
            return {"revisions": [logbook_serializers.revision_to_dict(revision) for revision in revisions]}
        finally:
            db.close()

    @router.get("/entry/{entry_id}/revisions/{revision_id}")
    def get_entry_revision(request: Request, entry_id: str, revision_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            logbook_repo.load_entry_or_404(db, owner, entry_id)
            revision = logbook_repo.load_entry_revision_or_404(db, owner, entry_id, revision_id)
            return logbook_serializers.revision_to_dict(revision, full=True)
        finally:
            db.close()

    @router.post("/entry/{entry_id}/revisions/{revision_id}/restore")
    def restore_entry_revision(request: Request, entry_id: str, revision_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            revision = logbook_repo.load_entry_revision_or_404(db, owner, entry_id, revision_id)
            logbook_repo.create_entry_revision(
                db,
                entry,
                source="restore",
                reason=f"Before restoring revision {revision_id}",
            )
            logbook_repo.restore_entry_revision(db, owner, entry, revision)
            db.commit()
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
            return {
                "ok": True,
                "entry": logbook_serializers.entry_to_dict(entry),
                "revision": logbook_serializers.revision_to_dict(revision),
            }
        finally:
            db.close()

    @router.delete("/entry/{entry_id}")
    def delete_entry(request: Request, entry_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            db.delete(entry)
            db.commit()
            return {"ok": True}
        finally:
            db.close()

    @router.post("/entry/{entry_id}/apply-suggestions")
    def apply_entry_suggestions(request: Request, entry_id: str, body: LogbookApplySuggestions):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            people = []
            locations = []
            for item in body.people_suggestions or []:
                person = logbook_repo.link_person_suggestion(db, owner, entry, item.dict(exclude_none=True))
                if person:
                    people.append(person)
            for item in body.location_suggestions or []:
                location = logbook_repo.link_location_suggestion(db, owner, entry, item.dict(exclude_none=True))
                if location:
                    locations.append(location)
            db.commit()
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
            return {
                "ok": True,
                "entry": logbook_serializers.entry_to_dict(entry),
                "people": [logbook_serializers.person_to_dict(person) for person in people],
                "locations": [logbook_serializers.location_to_dict(location) for location in locations],
            }
        finally:
            db.close()

    @router.get("/contacts/candidates")
    def contact_candidates(request: Request, q: Optional[str] = None):
        owner = _owner(request)
        if not _contacts_allowed(owner):
            return {"contacts": [], "available": False}
        term = (q or "").strip()
        contacts = contacts_service.search_contacts(term, limit=20) if term else contacts_service.fetch_contacts()[:20]
        return {"contacts": [_contact_to_candidate(c) for c in contacts], "available": True}

    @router.get("/people")
    def list_people(request: Request, q: Optional[str] = None):
        owner = _owner(request)
        db = SessionLocal()
        try:
            people = logbook_repo.person_query(db, owner).all()
            stats = logbook_repo.person_stats(db, owner)
            term = logbook_utils.canonical_name(q or "")
            if term:
                people = [
                    p for p in people
                    if term in p.canonical_name or any(term in logbook_utils.canonical_name(a) for a in logbook_utils.aliases(p))
                ]
            def score(person: LogbookPerson):
                if not term:
                    return (1, person.display_name.lower())
                aliases = [logbook_utils.canonical_name(a) for a in logbook_utils.aliases(person)]
                exact = person.canonical_name == term or term in aliases
                prefix = person.canonical_name.startswith(term) or any(a.startswith(term) for a in aliases)
                return (0 if exact else 1 if prefix else 2, person.display_name.lower())
            people.sort(key=score)
            return {"people": _people_with_connection_summaries(db, owner, people, stats)}
        finally:
            db.close()

    @router.post("/people")
    def create_person(request: Request, body: LogbookPersonCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            existing = logbook_repo.find_person(db, owner, body.display_name)
            person = logbook_repo.get_or_create_person(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            if body.notes is not None:
                person.notes = body.notes
            if body.relationship_label is not None:
                person.relationship_label = _clean_optional(body.relationship_label)
            if body.llm_context is not None:
                person.llm_context = _clean_optional(body.llm_context)
            if body.contact_uid:
                _apply_contact_link(person, _load_contact_or_404(owner, body.contact_uid))
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.get("/people/{person_id}")
    def get_person(request: Request, person_id: str, limit: int = 20):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            entries = logbook_repo.entries_for_person(db, owner, person.id, limit=limit)
            connections = logbook_repo.connections_for_people(
                db,
                owner,
                [person.id],
                include_hidden=True,
                limit_per_person=100,
            ).get(person.id, [])
            person_data = logbook_utils.with_stats(
                logbook_serializers.person_to_dict(person),
                logbook_repo.person_stats(db, owner).get(person.id, {}),
            )
            person_data["connections_summary"] = [
                summary for conn in connections
                if (summary := logbook_serializers.connection_summary_to_dict(conn, person.id))
            ]
            facts = logbook_repo.person_facts(db, owner, person.id, include_inactive=True, limit=100)
            person_data["facts"] = [logbook_serializers.person_fact_to_dict(fact) for fact in facts]
            return {
                "person": person_data,
                "entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries],
                "connections": [logbook_serializers.connection_to_dict(conn) for conn in connections],
                "facts": person_data["facts"],
            }
        finally:
            db.close()

    @router.get("/people/{person_id}/entries")
    def person_entries(request: Request, person_id: str, limit: int = 50):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            entries = logbook_repo.entries_for_person(db, owner, person.id, limit=limit)
            return {"entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries]}
        finally:
            db.close()

    @router.post("/people/{person_id}/facts")
    def create_person_fact(request: Request, person_id: str, body: LogbookPersonFactCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            value_text = _clean_optional(body.value_text)
            if not value_text:
                raise HTTPException(400, "Fact value is required")
            fact, duplicate = logbook_repo.upsert_person_fact(
                db,
                owner,
                person,
                fact_type=body.fact_type,
                label=body.label,
                value_text=value_text,
                value_json=body.value_json,
                confidence=body.confidence,
                source="manual",
                status=body.status or "active",
            )
            if not fact:
                raise HTTPException(400, "Fact value is required")
            db.commit()
            return {
                "ok": True,
                "duplicate": duplicate,
                "fact": logbook_serializers.person_fact_to_dict(fact),
            }
        finally:
            db.close()

    @router.put("/people/{person_id}")
    def update_person(request: Request, person_id: str, body: LogbookPersonUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            fields_set = getattr(body, "__fields_set__", getattr(body, "model_fields_set", set()))
            if body.display_name is not None:
                canonical = logbook_utils.canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                duplicate = logbook_repo.person_query(db, owner).filter(
                    LogbookPerson.canonical_name == canonical,
                    LogbookPerson.id != person.id,
                ).first()
                if duplicate:
                    raise HTTPException(409, "A person with that name already exists")
                person.display_name = body.display_name.strip()
                person.canonical_name = canonical
            if body.aliases is not None:
                aliases = [a.strip() for a in body.aliases if str(a).strip()]
                person.aliases = json.dumps(aliases, ensure_ascii=False) if aliases else None
            if "notes" in fields_set:
                person.notes = body.notes
            if "relationship_label" in fields_set:
                person.relationship_label = _clean_optional(body.relationship_label)
            if "llm_context" in fields_set:
                person.llm_context = _clean_optional(body.llm_context)
            if "contact_uid" in fields_set:
                if body.contact_uid:
                    _apply_contact_link(person, _load_contact_or_404(owner, body.contact_uid))
                else:
                    _clear_contact_link(person)
            if "contact_source" in fields_set:
                person.contact_source = _clean_optional(body.contact_source)
            if "contact_snapshot_json" in fields_set:
                person.contact_snapshot_json = json.dumps(body.contact_snapshot_json, ensure_ascii=False) if body.contact_snapshot_json else None
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/{person_id}/link-contact")
    def link_person_contact(request: Request, person_id: str, body: LogbookPersonContactLink):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            contact = _load_contact_or_404(owner, body.contact_uid)
            _apply_contact_link(person, contact)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/{person_id}/unlink-contact")
    def unlink_person_contact(request: Request, person_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            _clear_contact_link(person)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/merge")
    def merge_people(request: Request, body: LogbookPeopleMerge):
        owner = _owner(request)
        if body.source_person_id == body.target_person_id:
            raise HTTPException(400, "Choose two different people")
        db = SessionLocal()
        try:
            source = logbook_repo.load_person_or_404(db, owner, body.source_person_id)
            target = logbook_repo.load_person_or_404(db, owner, body.target_person_id)
            db.query(LogbookMention).filter(LogbookMention.person_id == source.id).update(
                {LogbookMention.person_id: target.id},
                synchronize_session=False,
            )
            source_connections = db.query(LogbookPersonConnection).filter(
                LogbookPersonConnection.owner == owner,
                or_(
                    LogbookPersonConnection.person_a_id == source.id,
                    LogbookPersonConnection.person_b_id == source.id,
                )
            ).all()
            for conn in source_connections:
                other_id = conn.person_b_id if conn.person_a_id == source.id else conn.person_a_id
                pair = logbook_utils.pair_ids(target.id, other_id)
                if not pair:
                    db.delete(conn)
                    continue
                a_id, b_id = pair
                existing = db.query(LogbookPersonConnection).filter(
                    LogbookPersonConnection.owner == owner,
                    LogbookPersonConnection.person_a_id == a_id,
                    LogbookPersonConnection.person_b_id == b_id,
                    LogbookPersonConnection.connection_type == conn.connection_type,
                    LogbookPersonConnection.id != conn.id,
                ).first()
                if existing:
                    evidence = logbook_utils.json_load(existing.evidence_json, []) + logbook_utils.json_load(conn.evidence_json, [])
                    deduped = []
                    seen = set()
                    for item in evidence:
                        if not isinstance(item, dict):
                            continue
                        key = (item.get("entry_id"), item.get("source", "logbook"))
                        if key in seen:
                            continue
                        seen.add(key)
                        deduped.append(item)
                    existing.evidence_json = json.dumps(deduped[-8:], ensure_ascii=False)
                    existing.strength = max(existing.strength or 1, conn.strength or 1)
                    existing.confidence = max(existing.confidence or 0, conn.confidence or 0)
                    if existing.status != "accepted" and conn.status == "accepted":
                        existing.status = "accepted"
                    db.delete(conn)
                else:
                    conn.person_a_id = a_id
                    conn.person_b_id = b_id
            logbook_repo.merge_aliases(target, [source.display_name] + logbook_utils.aliases(source))
            if source.notes and not target.notes:
                target.notes = source.notes
            if source.relationship_label and not target.relationship_label:
                target.relationship_label = source.relationship_label
            if source.llm_context:
                if not target.llm_context:
                    target.llm_context = source.llm_context
                elif source.llm_context not in target.llm_context:
                    target.llm_context = f"{target.llm_context}\n\n{source.llm_context}"
            if source.contact_uid and not target.contact_uid:
                target.contact_uid = source.contact_uid
                target.contact_source = source.contact_source
                target.contact_snapshot_json = source.contact_snapshot_json
            fact_merge = logbook_repo.merge_person_facts(db, owner, source.id, target)
            db.delete(source)
            db.commit()
            return {
                "ok": True,
                "person": logbook_serializers.person_to_dict(target),
                "facts": fact_merge,
            }
        finally:
            db.close()

    @router.get("/locations")
    def list_locations(request: Request, q: Optional[str] = None, include_hidden: bool = False):
        owner = _owner(request)
        db = SessionLocal()
        try:
            locations = logbook_repo.location_query(db, owner, include_hidden=include_hidden).all()
            stats = logbook_repo.location_stats(db, owner)
            term = logbook_utils.canonical_name(q or "")
            if term:
                locations = [
                    loc for loc in locations
                    if term in loc.canonical_name or any(term in logbook_utils.canonical_name(a) for a in logbook_utils.aliases(loc))
                ]
            def score(location: LogbookLocation):
                if not term:
                    return (1, location.display_name.lower())
                aliases = [logbook_utils.canonical_name(a) for a in logbook_utils.aliases(location)]
                exact = location.canonical_name == term or term in aliases
                prefix = location.canonical_name.startswith(term) or any(a.startswith(term) for a in aliases)
                return (0 if exact else 1 if prefix else 2, location.display_name.lower())
            locations.sort(key=score)
            return {"locations": [logbook_utils.with_stats(logbook_serializers.location_to_dict(loc), stats.get(loc.id, {})) for loc in locations]}
        finally:
            db.close()

    @router.post("/locations")
    def create_location(request: Request, body: LogbookLocationCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            existing = logbook_repo.find_location_duplicate(
                db,
                owner,
                [body.display_name, *(body.aliases or [])],
            )
            if existing:
                return {"ok": True, "duplicate": True, "location": logbook_serializers.location_to_dict(existing)}
            location = logbook_repo.get_or_create_location(db, owner, body.display_name, body.aliases, body.notes)
            if body.notes is not None:
                location.notes = body.notes
            if body.address is not None:
                location.address = _clean_optional(body.address)
            if body.latitude is not None:
                location.latitude = body.latitude
            if body.longitude is not None:
                location.longitude = body.longitude
            if body.location_type is not None:
                location.location_type = _clean_optional(body.location_type)
            if body.llm_context is not None:
                location.llm_context = _clean_optional(body.llm_context)
            db.commit()
            return {"ok": True, "duplicate": False, "location": logbook_serializers.location_to_dict(location)}
        finally:
            db.close()

    @router.get("/locations/{location_id}")
    def get_location(request: Request, location_id: str, limit: int = 20):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            entries = logbook_repo.entries_for_location(db, owner, location.id, limit=limit)
            return {
                "location": logbook_utils.with_stats(
                    logbook_serializers.location_to_dict(location),
                    logbook_repo.location_stats(db, owner).get(location.id, {}),
                ),
                "entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries],
            }
        finally:
            db.close()

    @router.get("/locations/{location_id}/entries")
    def location_entries(request: Request, location_id: str, limit: int = 50):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            entries = logbook_repo.entries_for_location(db, owner, location.id, limit=limit)
            return {"entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries]}
        finally:
            db.close()

    @router.put("/locations/{location_id}")
    def update_location(request: Request, location_id: str, body: LogbookLocationUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            fields_set = getattr(body, "__fields_set__", getattr(body, "model_fields_set", set()))
            candidate_names = [
                body.display_name if body.display_name is not None else location.display_name,
                *(body.aliases if body.aliases is not None else logbook_utils.aliases(location)),
            ]
            duplicate = logbook_repo.find_location_duplicate(
                db,
                owner,
                candidate_names,
                exclude_id=location.id,
            )
            if duplicate:
                raise HTTPException(409, "A location with that name or alias already exists")
            if body.display_name is not None:
                canonical = logbook_utils.canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                location.display_name = body.display_name.strip()
                location.canonical_name = canonical
            if body.aliases is not None:
                aliases = [a.strip() for a in body.aliases if str(a).strip()]
                location.aliases = json.dumps(aliases, ensure_ascii=False) if aliases else None
            if "notes" in fields_set:
                location.notes = body.notes
            if "address" in fields_set:
                location.address = _clean_optional(body.address)
            if "latitude" in fields_set:
                location.latitude = body.latitude
            if "longitude" in fields_set:
                location.longitude = body.longitude
            if "location_type" in fields_set:
                location.location_type = _clean_optional(body.location_type)
            if "llm_context" in fields_set:
                location.llm_context = _clean_optional(body.llm_context)
            if "hidden" in fields_set:
                location.hidden = bool(body.hidden)
            db.commit()
            return {"ok": True, "location": logbook_serializers.location_to_dict(location)}
        finally:
            db.close()

    @router.post("/locations/{location_id}/hide")
    def hide_location(request: Request, location_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            location.hidden = True
            db.commit()
            return {"ok": True, "location": logbook_serializers.location_to_dict(location)}
        finally:
            db.close()

    @router.post("/locations/{location_id}/unhide")
    def unhide_location(request: Request, location_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            location.hidden = False
            db.commit()
            return {"ok": True, "location": logbook_serializers.location_to_dict(location)}
        finally:
            db.close()

    @router.delete("/locations/{location_id}")
    def delete_location(request: Request, location_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            if logbook_repo.location_mention_count(db, location.id):
                raise HTTPException(409, "Place has linked entries; hide it instead")
            db.delete(location)
            db.commit()
            return {"ok": True, "deleted": True, "id": location_id}
        finally:
            db.close()

    @router.post("/locations/merge")
    def merge_locations(request: Request, body: LogbookLocationsMerge):
        owner = _owner(request)
        if body.source_location_id == body.target_location_id:
            raise HTTPException(400, "Choose two different locations")
        db = SessionLocal()
        try:
            source = logbook_repo.load_location_or_404(db, owner, body.source_location_id)
            target = logbook_repo.load_location_or_404(db, owner, body.target_location_id)
            db.query(LogbookLocationMention).filter(LogbookLocationMention.location_id == source.id).update(
                {LogbookLocationMention.location_id: target.id},
                synchronize_session=False,
            )
            logbook_repo.merge_location_aliases(target, [source.display_name] + logbook_utils.aliases(source))
            if source.notes and not target.notes:
                target.notes = source.notes
            if source.address and not target.address:
                target.address = source.address
            if source.latitude is not None and target.latitude is None:
                target.latitude = source.latitude
            if source.longitude is not None and target.longitude is None:
                target.longitude = source.longitude
            if source.location_type and not target.location_type:
                target.location_type = source.location_type
            if source.llm_context:
                if not target.llm_context:
                    target.llm_context = source.llm_context
                elif source.llm_context not in target.llm_context:
                    target.llm_context = f"{target.llm_context}\n\n{source.llm_context}"
            db.delete(source)
            db.commit()
            return {"ok": True, "location": logbook_serializers.location_to_dict(target)}
        finally:
            db.close()

    @router.get("/connections")
    def list_connections(
        request: Request,
        person_id: Optional[str] = None,
        status: Optional[str] = None,
    ):
        owner = _owner(request)
        db = SessionLocal()
        try:
            query = db.query(LogbookPersonConnection).options(
                selectinload(LogbookPersonConnection.person_a),
                selectinload(LogbookPersonConnection.person_b),
            ).filter(LogbookPersonConnection.owner == owner)
            if person_id:
                query = query.filter(or_(
                    LogbookPersonConnection.person_a_id == person_id,
                    LogbookPersonConnection.person_b_id == person_id,
                ))
            if status:
                query = query.filter(LogbookPersonConnection.status == status)
            conns = query.order_by(LogbookPersonConnection.updated_at.desc()).all()
            return {"connections": [logbook_serializers.connection_to_dict(conn) for conn in conns]}
        finally:
            db.close()

    @router.post("/connections")
    def create_connection(request: Request, body: LogbookConnectionCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn, duplicate = logbook_repo.upsert_manual_connection(
                db,
                owner,
                person_a_id=body.person_a_id,
                person_b_id=body.person_b_id,
                connection_type=body.connection_type,
                description=body.description,
                strength=body.strength,
                confidence=body.confidence,
                status=body.status,
            )
            db.commit()
            return {
                "ok": True,
                "duplicate": duplicate,
                "connection": logbook_serializers.connection_to_dict(conn),
            }
        finally:
            db.close()

    @router.put("/connections/{connection_id}")
    def update_connection(request: Request, connection_id: str, body: LogbookConnectionUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn = logbook_repo.load_connection_or_404(db, owner, connection_id)
            fields_set = getattr(body, "__fields_set__", getattr(body, "model_fields_set", set()))
            conn = logbook_repo.update_manual_connection(
                db,
                owner,
                conn,
                connection_type=body.connection_type,
                description=body.description,
                strength=body.strength,
                confidence=body.confidence,
                status=body.status,
                fields_set=fields_set,
            )
            db.commit()
            return {"ok": True, "connection": logbook_serializers.connection_to_dict(conn)}
        finally:
            db.close()

    @router.post("/connections/{connection_id}/accept")
    def accept_connection(request: Request, connection_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn = logbook_repo.load_connection_or_404(db, owner, connection_id)
            conn.status = "accepted"
            db.commit()
            return {"ok": True, "connection": logbook_serializers.connection_to_dict(conn)}
        finally:
            db.close()

    @router.post("/connections/{connection_id}/hide")
    def hide_connection(request: Request, connection_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn = logbook_repo.load_connection_or_404(db, owner, connection_id)
            conn.status = "hidden"
            db.commit()
            return {"ok": True, "connection": logbook_serializers.connection_to_dict(conn)}
        finally:
            db.close()

    @router.get("/ai/status")
    def ai_status(request: Request):
        owner = _owner(request)
        return logbook_ai.ai_status(owner)

    @router.post("/ai/assist")
    async def ai_assist(request: Request, body: LogbookAIAssist):
        owner = _owner(request)
        return await logbook_ai.run_ai_assist(owner, body)

    @router.post("/ai/analyze-entry/{entry_id}")
    async def analyze_entry(request: Request, entry_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = logbook_repo.load_entry_or_404(db, owner, entry_id)
            payload = LogbookAIAssist(
                entry_date=entry.entry_date,
                content=entry.content or "",
                mode="extract_all",
                locale="en",
                current_entry=logbook_serializers.entry_to_dict(entry),
            )
            result = await logbook_ai.run_ai_assist(owner, payload)
            if isinstance(result, JSONResponse):
                return result
            updated_people = logbook_ai.store_ai_person_suggestion_details(db, owner, entry, result.get("people_suggestions") or [])
            stored = logbook_ai.store_ai_connection_suggestions(db, owner, entry, result.get("connection_suggestions") or [])
            db.commit()
            result["updated_people"] = [logbook_serializers.person_to_dict(person) for person in updated_people]
            result["stored_connections"] = [logbook_serializers.connection_to_dict(c) for c in stored]
            return result
        finally:
            db.close()

    return router
