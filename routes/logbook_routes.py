"""Daily Logbook API."""

import json
import uuid
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
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
from src.logbook import ai as logbook_ai
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from src.logbook.schemas import (
    LogbookAIAssist,
    LogbookEntryUpdate,
    LogbookEntryUpsert,
    LogbookLocationCreate,
    LogbookLocationsMerge,
    LogbookLocationUpdate,
    LogbookPeopleMerge,
    LogbookPersonCreate,
    LogbookPersonUpdate,
)


def _owner(request: Request) -> str:
    require_user(request)
    return effective_user(request) or ""


def setup_logbook_routes() -> APIRouter:
    router = APIRouter(prefix="/api/logbook", tags=["logbook"])

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
            content_changed = logbook_repo.apply_entry_fields(entry, body)
            if body.datapoints is not None:
                logbook_repo.replace_datapoints(db, entry, body.datapoints)
            if content_changed or not entry.mentions or not entry.location_mentions:
                logbook_repo.rebuild_entry_links(db, owner, entry)
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
            content_changed = logbook_repo.apply_entry_fields(entry, body)
            if body.datapoints is not None:
                logbook_repo.replace_datapoints(db, entry, body.datapoints)
            if content_changed:
                logbook_repo.rebuild_entry_links(db, owner, entry)
            db.commit()
            entry = logbook_repo.entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
            return logbook_serializers.entry_to_dict(entry)
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
            return {"people": [logbook_utils.with_stats(logbook_serializers.person_to_dict(p), stats.get(p.id, {})) for p in people]}
        finally:
            db.close()

    @router.post("/people")
    def create_person(request: Request, body: LogbookPersonCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            existing = logbook_repo.find_person(db, owner, body.display_name)
            person = logbook_repo.get_or_create_person(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.put("/people/{person_id}")
    def update_person(request: Request, person_id: str, body: LogbookPersonUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
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
            if body.notes is not None:
                person.notes = body.notes
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
            db.delete(source)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(target)}
        finally:
            db.close()

    @router.get("/locations")
    def list_locations(request: Request, q: Optional[str] = None):
        owner = _owner(request)
        db = SessionLocal()
        try:
            locations = logbook_repo.location_query(db, owner).all()
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
            existing = logbook_repo.find_location(db, owner, body.display_name)
            location = logbook_repo.get_or_create_location(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "location": logbook_serializers.location_to_dict(location)}
        finally:
            db.close()

    @router.put("/locations/{location_id}")
    def update_location(request: Request, location_id: str, body: LogbookLocationUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = logbook_repo.load_location_or_404(db, owner, location_id)
            if body.display_name is not None:
                canonical = logbook_utils.canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                duplicate = logbook_repo.location_query(db, owner).filter(
                    LogbookLocation.canonical_name == canonical,
                    LogbookLocation.id != location.id,
                ).first()
                if duplicate:
                    raise HTTPException(409, "A location with that name already exists")
                location.display_name = body.display_name.strip()
                location.canonical_name = canonical
            if body.aliases is not None:
                aliases = [a.strip() for a in body.aliases if str(a).strip()]
                location.aliases = json.dumps(aliases, ensure_ascii=False) if aliases else None
            if body.notes is not None:
                location.notes = body.notes
            db.commit()
            return {"ok": True, "location": logbook_serializers.location_to_dict(location)}
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
            stored = logbook_ai.store_ai_connection_suggestions(db, owner, entry, result.get("connection_suggestions") or [])
            db.commit()
            result["stored_connections"] = [logbook_serializers.connection_to_dict(c) for c in stored]
            return result
        finally:
            db.close()

    return router
