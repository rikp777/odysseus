"""Daily Logbook people and contact API routes."""

from collections.abc import Callable
import json
from typing import Optional

from fastapi import APIRouter, HTTPException, Request
from sqlalchemy import or_

from core.database import LogbookMention, LogbookPerson, LogbookPersonConnection, SessionLocal
from src.contacts import service as contacts_service
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from src.logbook.schemas import (
    LogbookPeopleMerge,
    LogbookPersonContactLink,
    LogbookPersonCreate,
    LogbookPersonFactCreate,
    LogbookPersonUpdate,
)
from src.tool_security import owner_is_admin_or_single_user


def clean_optional(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def contacts_allowed(owner: str) -> bool:
    try:
        return owner_is_admin_or_single_user(owner or None)
    except Exception:
        return not bool(owner)


def contact_to_candidate(contact: dict) -> dict:
    return {
        "uid": str(contact.get("uid") or ""),
        "name": contact.get("name") or "",
        "emails": contact.get("emails") or [],
        "phones": contact.get("phones") or [],
        "source": "contacts",
    }


def load_contact_or_404(owner: str, contact_uid: str) -> dict:
    if not contacts_allowed(owner):
        raise HTTPException(403, "Contacts are not available for this user")
    uid = str(contact_uid or "").strip()
    if not uid:
        raise HTTPException(400, "contact_uid is required")
    for contact in contacts_service.fetch_contacts(force=True):
        if str(contact.get("uid") or "") == uid:
            return contact
    raise HTTPException(404, "Contact not found")


def apply_contact_link(person: LogbookPerson, contact: dict) -> None:
    person.contact_uid = str(contact.get("uid") or "") or None
    person.contact_source = "contacts"
    person.contact_snapshot_json = json.dumps(contact_to_candidate(contact), ensure_ascii=False)
    if not person.display_name and contact.get("name"):
        person.display_name = str(contact["name"]).strip()


def clear_contact_link(person: LogbookPerson) -> None:
    person.contact_uid = None
    person.contact_source = None
    person.contact_snapshot_json = None


def people_with_connection_summaries(db, owner: str, people, stats=None, *, limit_per_person: int = 4):
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


def register_logbook_people_routes(
    router: APIRouter,
    *,
    owner_func: Callable[[Request], str],
    session_factory: Callable[[], object] = SessionLocal,
) -> None:
    @router.get("/contacts/candidates")
    def contact_candidates(request: Request, q: Optional[str] = None):
        owner = owner_func(request)
        if not contacts_allowed(owner):
            return {"contacts": [], "available": False}
        term = (q or "").strip()
        contacts = contacts_service.search_contacts(term, limit=20) if term else contacts_service.fetch_contacts()[:20]
        return {"contacts": [contact_to_candidate(c) for c in contacts], "available": True}

    @router.get("/people")
    def list_people(request: Request, q: Optional[str] = None):
        owner = owner_func(request)
        db = session_factory()
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
            return {"people": people_with_connection_summaries(db, owner, people, stats)}
        finally:
            db.close()

    @router.post("/people")
    def create_person(request: Request, body: LogbookPersonCreate):
        owner = owner_func(request)
        db = session_factory()
        try:
            existing = logbook_repo.find_person(db, owner, body.display_name)
            person = logbook_repo.get_or_create_person(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            if body.notes is not None:
                person.notes = body.notes
            if body.relationship_label is not None:
                person.relationship_label = clean_optional(body.relationship_label)
            if body.llm_context is not None:
                person.llm_context = clean_optional(body.llm_context)
            if body.contact_uid:
                apply_contact_link(person, load_contact_or_404(owner, body.contact_uid))
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.get("/people/{person_id}")
    def get_person(request: Request, person_id: str, limit: int = 20):
        owner = owner_func(request)
        db = session_factory()
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
        owner = owner_func(request)
        db = session_factory()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            entries = logbook_repo.entries_for_person(db, owner, person.id, limit=limit)
            return {"entries": [logbook_serializers.entry_to_dict(entry, full=False) for entry in entries]}
        finally:
            db.close()

    @router.post("/people/{person_id}/facts")
    def create_person_fact(request: Request, person_id: str, body: LogbookPersonFactCreate):
        owner = owner_func(request)
        db = session_factory()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            value_text = clean_optional(body.value_text)
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
        owner = owner_func(request)
        db = session_factory()
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
                person.relationship_label = clean_optional(body.relationship_label)
            if "llm_context" in fields_set:
                person.llm_context = clean_optional(body.llm_context)
            if "contact_uid" in fields_set:
                if body.contact_uid:
                    apply_contact_link(person, load_contact_or_404(owner, body.contact_uid))
                else:
                    clear_contact_link(person)
            if "contact_source" in fields_set:
                person.contact_source = clean_optional(body.contact_source)
            if "contact_snapshot_json" in fields_set:
                person.contact_snapshot_json = json.dumps(body.contact_snapshot_json, ensure_ascii=False) if body.contact_snapshot_json else None
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/{person_id}/link-contact")
    def link_person_contact(request: Request, person_id: str, body: LogbookPersonContactLink):
        owner = owner_func(request)
        db = session_factory()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            contact = load_contact_or_404(owner, body.contact_uid)
            apply_contact_link(person, contact)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/{person_id}/unlink-contact")
    def unlink_person_contact(request: Request, person_id: str):
        owner = owner_func(request)
        db = session_factory()
        try:
            person = logbook_repo.load_person_or_404(db, owner, person_id)
            clear_contact_link(person)
            db.commit()
            return {"ok": True, "person": logbook_serializers.person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/merge")
    def merge_people(request: Request, body: LogbookPeopleMerge):
        owner = owner_func(request)
        if body.source_person_id == body.target_person_id:
            raise HTTPException(400, "Choose two different people")
        db = session_factory()
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
