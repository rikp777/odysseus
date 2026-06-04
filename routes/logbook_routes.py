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
from src.contacts import service as contacts_service
from src.logbook import ai as logbook_ai
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from src.tool_security import owner_is_admin_or_single_user
from src.logbook.schemas import (
    LogbookApplySuggestions,
    LogbookAIAssist,
    LogbookEntryUpdate,
    LogbookEntryUpsert,
    LogbookLocationCreate,
    LogbookLocationsMerge,
    LogbookLocationUpdate,
    LogbookPeopleMerge,
    LogbookPersonContactLink,
    LogbookPersonCreate,
    LogbookPersonUpdate,
)


def _owner(request: Request) -> str:
    require_user(request)
    return effective_user(request) or ""


def _clean_optional(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


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
                "people": [
                    logbook_utils.with_stats(logbook_serializers.person_to_dict(person), person_stats.get(person.id, {}))
                    for person in people
                ],
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
            connections = db.query(LogbookPersonConnection).options(
                selectinload(LogbookPersonConnection.person_a),
                selectinload(LogbookPersonConnection.person_b),
            ).filter(
                LogbookPersonConnection.owner == owner,
                or_(
                    LogbookPersonConnection.person_a_id == person.id,
                    LogbookPersonConnection.person_b_id == person.id,
                ),
            ).order_by(LogbookPersonConnection.updated_at.desc()).all()
            return {
                "person": logbook_utils.with_stats(
                    logbook_serializers.person_to_dict(person),
                    logbook_repo.person_stats(db, owner).get(person.id, {}),
                ),
                "entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries],
                "connections": [logbook_serializers.connection_to_dict(conn) for conn in connections],
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
            db.delete(source)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(target)}
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
            existing = logbook_repo.find_location(db, owner, body.display_name, include_hidden=True)
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
            if body.display_name is not None:
                canonical = logbook_utils.canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                duplicate = logbook_repo.location_query(db, owner, include_hidden=True).filter(
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
            mention_count = db.query(LogbookLocationMention.id).filter(
                LogbookLocationMention.location_id == location.id,
            ).count()
            if mention_count:
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
            stored = logbook_ai.store_ai_connection_suggestions(db, owner, entry, result.get("connection_suggestions") or [])
            db.commit()
            result["stored_connections"] = [logbook_serializers.connection_to_dict(c) for c in stored]
            return result
        finally:
            db.close()

    return router
