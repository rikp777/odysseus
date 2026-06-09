"""Daily Logbook API."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import selectinload

from core.database import (
    LogbookDataPoint,
    LogbookEntry,
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
    LogbookPerson,
    LogbookPersonConnection,
    SessionLocal,
)
from src.auth_helpers import effective_user, require_user
from src.logbook import geocoding as logbook_geocoding
from src.logbook.map_tiles import map_tile_config
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from routes.logbook_ai_routes import register_logbook_ai_routes
from routes.logbook_people_routes import (
    contacts_allowed as _contacts_allowed,
    people_with_connection_summaries as _people_with_connection_summaries,
    register_logbook_people_routes,
)
from src.logbook.schemas import (
    LogbookApplySuggestions,
    LogbookConnectionCreate,
    LogbookConnectionUpdate,
    LogbookEntryUpdate,
    LogbookEntryUpsert,
    LogbookLocationCreate,
    LogbookLocationsMerge,
    LogbookLocationUpdate,
)

# Backwards-compatible alias for tests and in-process monkeypatches that used
# to patch routes.logbook_routes.httpx.AsyncClient directly.
httpx = logbook_geocoding.httpx


def _owner(request: Request) -> str:
    require_user(request)
    return effective_user(request) or ""


def _clean_optional(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


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
        return await logbook_geocoding.geocode_address(q, limit, session_factory=SessionLocal)

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

    register_logbook_people_routes(router, owner_func=_owner, session_factory=SessionLocal)

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

    register_logbook_ai_routes(router, owner_func=_owner, session_factory=SessionLocal)

    return router
