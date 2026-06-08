"""Daily Logbook database helpers.

The route layer should stay thin: open a session, call these owner-scoped
helpers, and serialize the response.
"""

from __future__ import annotations

import itertools
import json
import re
import uuid
from typing import Any, Dict, List, Optional

from fastapi import HTTPException
from pydantic import BaseModel
from sqlalchemy import func, or_
from sqlalchemy.orm import selectinload

from core.database import (
    LogbookDataPoint,
    LogbookEntry,
    LogbookEntryRevision,
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
    LogbookPerson,
    LogbookPersonConnection,
    LogbookPersonFact,
)
from src.logbook.schemas import (
    ALLOWED_CONNECTION_STATUS,
    ALLOWED_CONNECTION_TYPES,
    ALLOWED_PERSON_FACT_STATUS,
    ALLOWED_PERSON_FACT_TYPES,
    LogbookDataPointIn,
)
from src.logbook.utils import (
    add_evidence,
    aliases,
    canonical_name,
    clamp_confidence,
    clamp_score,
    clean_key,
    entry_snippet,
    json_dump,
    json_load,
    normalized_title,
    pair_ids,
    parse_data_links,
    parse_location_links,
    parse_locations,
    parse_mentions,
    parse_person_links,
)


def find_person(db, owner: str, name: str, people: Optional[List[LogbookPerson]] = None) -> Optional[LogbookPerson]:
    canonical = canonical_name(name)
    if not canonical:
        return None
    candidates = people
    if candidates is None:
        candidates = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    for person in candidates:
        if person.canonical_name == canonical:
            return person
        for alias in aliases(person):
            if canonical_name(alias) == canonical:
                return person
    return None


def merge_aliases(person: LogbookPerson, names: List[str]) -> None:
    existing = aliases(person)
    seen = {canonical_name(person.display_name), *[canonical_name(a) for a in existing]}
    for name in names:
        label = str(name or "").strip()
        canonical = canonical_name(label)
        if not label or not canonical or canonical in seen:
            continue
        existing.append(label)
        seen.add(canonical)
    person.aliases = json.dumps(existing, ensure_ascii=False) if existing else None


def get_or_create_person(
    db,
    owner: str,
    display_name: str,
    aliases_: Optional[List[str]] = None,
    notes: Optional[str] = None,
    *,
    update_existing: bool = False,
) -> LogbookPerson:
    name = re.sub(r"\s+", " ", (display_name or "").strip())
    canonical = canonical_name(name)
    if not canonical:
        raise HTTPException(400, "display_name is required")
    person = find_person(db, owner, name)
    if person:
        if update_existing:
            person.display_name = name
            person.canonical_name = canonical
            person.notes = notes
        if aliases_:
            merge_aliases(person, aliases_)
        db.flush()
        return person
    person = LogbookPerson(
        id=str(uuid.uuid4()),
        owner=owner,
        display_name=name,
        canonical_name=canonical,
        aliases=json.dumps([a for a in (aliases_ or []) if str(a).strip()], ensure_ascii=False) if aliases_ else None,
        notes=notes,
    )
    db.add(person)
    db.flush()
    return person


def _clean_person_context_text(value: Optional[str], *, max_length: int = 1200) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_length].strip() or None


def _append_unique_person_text(existing: Optional[str], addition: Optional[str]) -> Optional[str]:
    text = _clean_person_context_text(addition)
    if not text:
        return existing
    current = str(existing or "").strip()
    if not current:
        return text
    if text.lower() in current.lower():
        return current
    return f"{current}\n\n{text}"


def normalize_person_fact_type(value: Optional[str], default: str = "unknown") -> str:
    fact_type = str(value or default or "unknown").strip().lower().replace(" ", "_")
    if fact_type not in ALLOWED_PERSON_FACT_TYPES:
        fact_type = "unknown"
    return fact_type


def normalize_person_fact_status(value: Optional[str], default: str = "active") -> str:
    status = str(value or default or "active").strip().lower()
    if status not in ALLOWED_PERSON_FACT_STATUS:
        status = "active"
    return status


def _clean_person_fact_value(value: Optional[str], *, max_length: int = 500) -> Optional[str]:
    text = re.sub(r"\s+", " ", str(value or "").strip())
    return text[:max_length].strip() or None


def upsert_person_fact(
    db,
    owner: str,
    person: LogbookPerson,
    *,
    fact_type: Optional[str],
    value_text: Optional[str],
    entry: Optional[LogbookEntry] = None,
    label: Optional[str] = None,
    value_json: Any = None,
    confidence: Optional[int] = None,
    source: str = "ai",
    status: str = "active",
) -> tuple[Optional[LogbookPersonFact], bool]:
    value = _clean_person_fact_value(value_text)
    if not person or not person.id or not value:
        return None, False
    normalized_type = normalize_person_fact_type(fact_type)
    normalized_status = normalize_person_fact_status(status)
    clean_label = _clean_person_context_text(label, max_length=80) or normalized_type.replace("_", " ").title()
    source_name = _clean_person_context_text(source, max_length=40) or "ai"
    entry_id = getattr(entry, "id", None)
    entry_date = getattr(entry, "entry_date", None)
    query = db.query(LogbookPersonFact).filter(
        LogbookPersonFact.owner == owner,
        LogbookPersonFact.person_id == person.id,
        LogbookPersonFact.fact_type == normalized_type,
        func.lower(LogbookPersonFact.value_text) == value.lower(),
    )
    fact = query.first()
    duplicate = fact is not None
    if not fact:
        fact = LogbookPersonFact(
            id=str(uuid.uuid4()),
            owner=owner,
            person_id=person.id,
            fact_type=normalized_type,
            label=clean_label,
            value_text=value,
            value_json=json_dump(value_json),
            confidence=clamp_confidence(confidence, default=70),
            source=source_name,
            source_entry_id=entry_id,
            source_entry_date=entry_date,
            last_seen_entry_id=entry_id,
            last_seen_date=entry_date,
            status=normalized_status,
        )
        db.add(fact)
    else:
        fact.label = fact.label or clean_label
        if value_json is not None:
            fact.value_json = json_dump(value_json)
        fact.confidence = max(fact.confidence or 0, clamp_confidence(confidence, default=fact.confidence or 70))
        fact.source = fact.source or source_name
        if entry_id:
            fact.last_seen_entry_id = entry_id
        if entry_date:
            fact.last_seen_date = entry_date
        if normalized_status != "active" or fact.status not in ALLOWED_PERSON_FACT_STATUS:
            fact.status = normalized_status
    db.flush()
    return fact, duplicate


def person_facts(
    db,
    owner: str,
    person_id: str,
    *,
    include_inactive: bool = False,
    limit: int = 50,
) -> List[LogbookPersonFact]:
    limit = max(1, min(int(limit or 50), 200))
    query = db.query(LogbookPersonFact).filter(
        LogbookPersonFact.owner == owner,
        LogbookPersonFact.person_id == person_id,
    )
    if not include_inactive:
        query = query.filter(LogbookPersonFact.status == "active")
    return (
        query
        .order_by(LogbookPersonFact.last_seen_date.desc(), LogbookPersonFact.updated_at.desc())
        .limit(limit)
        .all()
    )


def person_facts_for_people(
    db,
    owner: str,
    person_ids: List[str],
    *,
    include_inactive: bool = False,
    limit_per_person: int = 3,
) -> Dict[str, List[LogbookPersonFact]]:
    ids = sorted({str(item) for item in person_ids or [] if item})
    if not ids:
        return {}
    limit = max(1, min(int(limit_per_person or 3), 20))
    query = db.query(LogbookPersonFact).filter(
        LogbookPersonFact.owner == owner,
        LogbookPersonFact.person_id.in_(ids),
    )
    if not include_inactive:
        query = query.filter(LogbookPersonFact.status == "active")
    rows = query.order_by(
        LogbookPersonFact.person_id.asc(),
        LogbookPersonFact.last_seen_date.desc(),
        LogbookPersonFact.updated_at.desc(),
    ).all()
    grouped: Dict[str, List[LogbookPersonFact]] = {person_id: [] for person_id in ids}
    for fact in rows:
        bucket = grouped.get(fact.person_id)
        if bucket is not None and len(bucket) < limit:
            bucket.append(fact)
    return grouped


def _fact_status_rank(status: Optional[str]) -> int:
    return {"active": 3, "archived": 2, "rejected": 1}.get(normalize_person_fact_status(status), 0)


def _earlier_fact_source(existing: LogbookPersonFact, incoming: LogbookPersonFact) -> tuple[Optional[str], Optional[str]]:
    existing_date = existing.source_entry_date or ""
    incoming_date = incoming.source_entry_date or ""
    if incoming_date and (not existing_date or incoming_date < existing_date):
        return incoming.source_entry_id, incoming.source_entry_date
    return existing.source_entry_id, existing.source_entry_date


def _later_fact_seen(existing: LogbookPersonFact, incoming: LogbookPersonFact) -> tuple[Optional[str], Optional[str]]:
    existing_date = existing.last_seen_date or ""
    incoming_date = incoming.last_seen_date or ""
    if incoming_date and (not existing_date or incoming_date > existing_date):
        return incoming.last_seen_entry_id, incoming.last_seen_date
    return existing.last_seen_entry_id, existing.last_seen_date


def merge_person_facts(db, owner: str, source_person_id: str, target: LogbookPerson) -> Dict[str, int]:
    moved = 0
    merged = 0
    if not source_person_id or not target or not target.id or source_person_id == target.id:
        return {"moved": moved, "merged": merged}
    facts = db.query(LogbookPersonFact).filter(
        LogbookPersonFact.owner == owner,
        LogbookPersonFact.person_id == source_person_id,
    ).all()
    for fact in facts:
        existing = db.query(LogbookPersonFact).filter(
            LogbookPersonFact.owner == owner,
            LogbookPersonFact.person_id == target.id,
            LogbookPersonFact.fact_type == fact.fact_type,
            func.lower(LogbookPersonFact.value_text) == str(fact.value_text or "").lower(),
            LogbookPersonFact.id != fact.id,
        ).first()
        if existing:
            existing.label = existing.label or fact.label
            if not existing.value_json and fact.value_json:
                existing.value_json = fact.value_json
            existing.confidence = max(existing.confidence or 0, fact.confidence or 0)
            existing.source = existing.source or fact.source
            existing.source_entry_id, existing.source_entry_date = _earlier_fact_source(existing, fact)
            existing.last_seen_entry_id, existing.last_seen_date = _later_fact_seen(existing, fact)
            if _fact_status_rank(fact.status) > _fact_status_rank(existing.status):
                existing.status = normalize_person_fact_status(fact.status)
            db.delete(fact)
            merged += 1
        else:
            fact.person_id = target.id
            moved += 1
    db.flush()
    return {"moved": moved, "merged": merged}


def apply_person_suggestion_fields(
    db,
    owner: str,
    person: LogbookPerson,
    suggestion: Dict[str, Any],
    *,
    entry: Optional[LogbookEntry] = None,
    source: str = "ai",
) -> List[LogbookPersonFact]:
    """Merge explicit AI person facts without overwriting manual context."""
    if not isinstance(suggestion, dict):
        return []
    relationship = _clean_person_context_text(suggestion.get("relationship_label"), max_length=80)
    if relationship and not person.relationship_label:
        person.relationship_label = relationship
    person.notes = _append_unique_person_text(person.notes, suggestion.get("notes"))
    person.llm_context = _append_unique_person_text(person.llm_context, suggestion.get("llm_context"))
    facts: List[LogbookPersonFact] = []
    for raw_fact in suggestion.get("facts") or []:
        if not isinstance(raw_fact, dict):
            continue
        fact, _duplicate = upsert_person_fact(
            db,
            owner,
            person,
            fact_type=raw_fact.get("fact_type"),
            label=raw_fact.get("label"),
            value_text=raw_fact.get("value_text"),
            value_json=raw_fact.get("value_json"),
            confidence=raw_fact.get("confidence", suggestion.get("confidence")),
            source=source,
            entry=entry,
        )
        if fact:
            facts.append(fact)
    return facts


def location_is_hidden(location: Optional[LogbookLocation]) -> bool:
    return bool(getattr(location, "hidden", False))


def find_location(
    db,
    owner: str,
    name: str,
    locations: Optional[List[LogbookLocation]] = None,
    *,
    include_hidden: bool = False,
) -> Optional[LogbookLocation]:
    canonical = canonical_name(name)
    if not canonical:
        return None
    candidates = locations
    if candidates is None:
        candidates = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    for location in candidates:
        if location_is_hidden(location) and not include_hidden:
            continue
        if location.canonical_name == canonical:
            return location
        for alias in aliases(location):
            if canonical_name(alias) == canonical:
                return location
    return None


def find_location_duplicate(
    db,
    owner: str,
    names: List[str],
    *,
    exclude_id: Optional[str] = None,
) -> Optional[LogbookLocation]:
    """Find an existing location that conflicts with any display name or alias."""
    candidates = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    for name in names or []:
        location = find_location(db, owner, name, candidates, include_hidden=True)
        if location and location.id != exclude_id:
            return location
    return None


def location_mention_count(db, location_id: str) -> int:
    return db.query(LogbookLocationMention.id).filter(
        LogbookLocationMention.location_id == location_id,
    ).count()


def merge_location_aliases(location: LogbookLocation, names: List[str]) -> None:
    existing = aliases(location)
    seen = {canonical_name(location.display_name), *[canonical_name(a) for a in existing]}
    for name in names:
        label = str(name or "").strip()
        canonical = canonical_name(label)
        if not label or not canonical or canonical in seen:
            continue
        existing.append(label)
        seen.add(canonical)
    location.aliases = json.dumps(existing, ensure_ascii=False) if existing else None


def get_or_create_location(
    db,
    owner: str,
    display_name: str,
    aliases_: Optional[List[str]] = None,
    notes: Optional[str] = None,
    *,
    update_existing: bool = False,
    include_hidden: bool = False,
) -> LogbookLocation:
    name = re.sub(r"\s+", " ", (display_name or "").strip())
    canonical = canonical_name(name)
    if not canonical:
        raise HTTPException(400, "display_name is required")
    location = find_location(db, owner, name, include_hidden=include_hidden)
    if location:
        if update_existing:
            location.display_name = name
            location.canonical_name = canonical
            location.notes = notes
        if aliases_:
            merge_location_aliases(location, aliases_)
        db.flush()
        return location
    location = LogbookLocation(
        id=str(uuid.uuid4()),
        owner=owner,
        display_name=name,
        canonical_name=canonical,
        aliases=json.dumps([a for a in (aliases_ or []) if str(a).strip()], ensure_ascii=False) if aliases_ else None,
        notes=notes,
    )
    db.add(location)
    db.flush()
    return location


def replace_datapoints(db, entry: LogbookEntry, datapoints: List[LogbookDataPointIn]) -> None:
    db.query(LogbookDataPoint).filter(LogbookDataPoint.entry_id == entry.id).delete(synchronize_session=False)
    for index, item in enumerate(datapoints or []):
        label = (item.label or "").strip() or None
        key = clean_key(item.key or label or "datapoint")
        db.add(LogbookDataPoint(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            key=key,
            label=label,
            value_text=item.value_text,
            value_number=item.value_number,
            unit=(item.unit or "").strip() or None,
            value_json=json_dump(item.value_json),
            sort_order=item.sort_order if item.sort_order is not None else index,
        ))


def _datapoint_snapshot(dp: Any, index: int = 0) -> Dict[str, Any]:
    value_json = getattr(dp, "value_json", None)
    return {
        "key": clean_key(getattr(dp, "key", "") or getattr(dp, "label", "") or "datapoint"),
        "label": (getattr(dp, "label", None) or "").strip() or None,
        "value_text": getattr(dp, "value_text", None),
        "value_number": getattr(dp, "value_number", None),
        "unit": (getattr(dp, "unit", None) or "").strip() or None,
        "value_json": json_load(value_json, None) if isinstance(value_json, str) else value_json,
        "sort_order": getattr(dp, "sort_order", None) if getattr(dp, "sort_order", None) is not None else index,
    }


def _datapoint_input_snapshot(item: LogbookDataPointIn, index: int = 0) -> Dict[str, Any]:
    label = (item.label or "").strip() or None
    return {
        "key": clean_key(item.key or label or "datapoint"),
        "label": label,
        "value_text": item.value_text,
        "value_number": item.value_number,
        "unit": (item.unit or "").strip() or None,
        "value_json": item.value_json,
        "sort_order": item.sort_order if item.sort_order is not None else index,
    }


def datapoint_snapshots(entry: LogbookEntry) -> List[Dict[str, Any]]:
    points = sorted(list(entry.datapoints or []), key=lambda dp: int(dp.sort_order or 0))
    return [_datapoint_snapshot(dp, index) for index, dp in enumerate(points)]


def entry_snapshot(entry: LogbookEntry) -> Dict[str, Any]:
    return {
        "title": normalized_title(entry.title),
        "content": entry.content or "",
        "summary": entry.summary,
        "mood_label": entry.mood_label,
        "mood_score": entry.mood_score,
        "energy_score": entry.energy_score,
        "stress_score": entry.stress_score,
        "ai_reflection": entry.ai_reflection,
        "datapoints": datapoint_snapshots(entry),
    }


def _snapshot_has_content(snapshot: Dict[str, Any]) -> bool:
    return any([
        snapshot.get("title") and snapshot.get("title") != "Daily log",
        str(snapshot.get("content") or "").strip(),
        snapshot.get("summary"),
        snapshot.get("mood_label"),
        snapshot.get("mood_score") is not None,
        snapshot.get("energy_score") is not None,
        snapshot.get("stress_score") is not None,
        snapshot.get("ai_reflection"),
        bool(snapshot.get("datapoints")),
    ])


def _model_data(body: BaseModel) -> Dict[str, Any]:
    if hasattr(body, "model_dump"):
        return body.model_dump(exclude_unset=True)
    return body.dict(exclude_unset=True)


def entry_will_change(entry: LogbookEntry, body: BaseModel) -> bool:
    data = _model_data(body)
    if "title" in data and normalized_title(data.get("title")) != normalized_title(entry.title):
        return True
    for field in ("content", "summary", "ai_reflection"):
        if field in data and (data.get(field) or "") != (getattr(entry, field, None) or ""):
            return True
    if "mood_label" in data and ((data.get("mood_label") or "").strip() or None) != entry.mood_label:
        return True
    for field in ("mood_score", "energy_score", "stress_score"):
        if field in data and clamp_score(data.get(field)) != getattr(entry, field, None):
            return True
    if body.datapoints is not None:
        incoming = [_datapoint_input_snapshot(item, index) for index, item in enumerate(body.datapoints or [])]
        if incoming != datapoint_snapshots(entry):
            return True
    return False


def create_entry_revision(
    db,
    entry: LogbookEntry,
    *,
    source: str = "manual_save",
    reason: Optional[str] = None,
) -> Optional[LogbookEntryRevision]:
    snapshot = entry_snapshot(entry)
    if not _snapshot_has_content(snapshot):
        return None
    revision = LogbookEntryRevision(
        id=str(uuid.uuid4()),
        entry_id=entry.id,
        owner=entry.owner,
        entry_date=entry.entry_date,
        source=(source or "manual_save")[:80],
        reason=reason,
        title=snapshot["title"],
        content=snapshot["content"],
        summary=snapshot["summary"],
        mood_label=snapshot["mood_label"],
        mood_score=snapshot["mood_score"],
        energy_score=snapshot["energy_score"],
        stress_score=snapshot["stress_score"],
        ai_reflection=snapshot["ai_reflection"],
        datapoints_json=json.dumps(snapshot["datapoints"], ensure_ascii=False),
    )
    db.add(revision)
    db.flush()
    return revision


def revision_query(db, owner: str, entry_id: str):
    return db.query(LogbookEntryRevision).filter(
        LogbookEntryRevision.owner == owner,
        LogbookEntryRevision.entry_id == entry_id,
    )


def entry_revisions(db, owner: str, entry_id: str, *, limit: int = 20) -> List[LogbookEntryRevision]:
    limit = max(1, min(int(limit or 20), 100))
    return (
        revision_query(db, owner, entry_id)
        .order_by(LogbookEntryRevision.created_at.desc())
        .limit(limit)
        .all()
    )


def load_entry_revision_or_404(db, owner: str, entry_id: str, revision_id: str) -> LogbookEntryRevision:
    revision = revision_query(db, owner, entry_id).filter(LogbookEntryRevision.id == revision_id).first()
    if not revision:
        raise HTTPException(404, "Logbook revision not found")
    return revision


def restore_entry_revision(db, owner: str, entry: LogbookEntry, revision: LogbookEntryRevision) -> None:
    entry.title = normalized_title(revision.title)
    entry.content = revision.content or ""
    entry.summary = revision.summary
    entry.mood_label = revision.mood_label
    entry.mood_score = clamp_score(revision.mood_score)
    entry.energy_score = clamp_score(revision.energy_score)
    entry.stress_score = clamp_score(revision.stress_score)
    entry.ai_reflection = revision.ai_reflection
    raw_datapoints = json_load(revision.datapoints_json, [])
    datapoints = [
        LogbookDataPointIn(**item)
        for item in raw_datapoints
        if isinstance(item, dict)
    ]
    replace_datapoints(db, entry, datapoints)
    rebuild_entry_links(db, owner, entry)
    sync_linked_datapoints(db, entry)


def sync_linked_datapoints(db, entry: LogbookEntry) -> None:
    links = parse_data_links(entry.content or "")
    if not links:
        return
    existing = db.query(LogbookDataPoint).filter(LogbookDataPoint.entry_id == entry.id).all()
    seen = {
        (str(dp.key or "").strip().lower(), str(dp.value_text or "").strip().lower())
        for dp in existing
    }
    sort_order = max([int(dp.sort_order or 0) for dp in existing] or [-1]) + 1
    for item in links:
        key = clean_key(item.get("key") or item.get("label") or "datapoint")
        value_text = str(item.get("value_text") or "").strip()
        if not key or not value_text:
            continue
        dedupe = (key.lower(), value_text.lower())
        if dedupe in seen:
            continue
        seen.add(dedupe)
        db.add(LogbookDataPoint(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            key=key,
            label=str(item.get("label") or "").strip() or key.replace("_", " ").title(),
            value_text=value_text,
            value_json=json_dump({
                "source": "markdown_link",
                "surface_text": item.get("surface_text"),
                "start_offset": item.get("start_offset"),
                "end_offset": item.get("end_offset"),
            }),
            sort_order=sort_order,
        ))
        sort_order += 1


def upsert_co_mentioned_connection(db, owner: str, entry: LogbookEntry, person_a_id: str, person_b_id: str, snippet: str) -> None:
    pair = pair_ids(person_a_id, person_b_id)
    if not pair:
        return
    a_id, b_id = pair
    conn = db.query(LogbookPersonConnection).filter(
        LogbookPersonConnection.owner == owner,
        LogbookPersonConnection.person_a_id == a_id,
        LogbookPersonConnection.person_b_id == b_id,
        LogbookPersonConnection.connection_type == "co_mentioned",
    ).first()
    if not conn:
        conn = LogbookPersonConnection(
            id=str(uuid.uuid4()),
            owner=owner,
            person_a_id=a_id,
            person_b_id=b_id,
            connection_type="co_mentioned",
            description="Mentioned together in daily log entries.",
            strength=1,
            confidence=60,
            evidence_json="[]",
            status="suggested",
        )
        db.add(conn)
    evidence = add_evidence(json_load(conn.evidence_json, []), entry, snippet)
    count = len(evidence)
    conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
    conn.strength = max(conn.strength or 1, min(5, 1 + max(0, count - 1) // 2))
    conn.confidence = max(conn.confidence or 0, min(90, 55 + count * 8))
    if conn.status not in ALLOWED_CONNECTION_STATUS:
        conn.status = "suggested"


def normalize_connection_type(value: Optional[str], default: str = "unknown") -> str:
    connection_type = str(value or default or "unknown").strip().lower().replace(" ", "_")
    if connection_type not in ALLOWED_CONNECTION_TYPES:
        raise HTTPException(400, "Unsupported connection type")
    return connection_type


def normalize_connection_status(value: Optional[str], default: str = "accepted") -> str:
    status = str(value or default or "accepted").strip().lower()
    if status not in ALLOWED_CONNECTION_STATUS:
        raise HTTPException(400, "Unsupported connection status")
    return status


def _clean_connection_description(value: Optional[str]) -> Optional[str]:
    text = str(value or "").strip()
    return text or None


def _apply_connection_fields(
    conn: LogbookPersonConnection,
    *,
    connection_type: Optional[str] = None,
    description: Optional[str] = None,
    strength: Optional[int] = None,
    confidence: Optional[int] = None,
    status: Optional[str] = None,
    fields_set: Optional[set] = None,
) -> None:
    fields = fields_set or {"connection_type", "description", "strength", "confidence", "status"}
    if "connection_type" in fields:
        conn.connection_type = normalize_connection_type(connection_type, conn.connection_type or "unknown")
    if "description" in fields:
        conn.description = _clean_connection_description(description)
    if "strength" in fields:
        conn.strength = clamp_score(strength, low=1, high=5) or 1
    if "confidence" in fields:
        conn.confidence = clamp_confidence(confidence, conn.confidence or 0)
    if "status" in fields:
        conn.status = normalize_connection_status(status, conn.status or "accepted")


def upsert_manual_connection(
    db,
    owner: str,
    *,
    person_a_id: str,
    person_b_id: str,
    connection_type: Optional[str] = "unknown",
    description: Optional[str] = None,
    strength: Optional[int] = None,
    confidence: Optional[int] = None,
    status: Optional[str] = "accepted",
) -> tuple[LogbookPersonConnection, bool]:
    person_a = load_person_or_404(db, owner, person_a_id)
    person_b = load_person_or_404(db, owner, person_b_id)
    pair = pair_ids(person_a.id, person_b.id)
    if not pair:
        raise HTTPException(400, "Choose two different people")
    a_id, b_id = pair
    normalized_type = normalize_connection_type(connection_type)
    conn = db.query(LogbookPersonConnection).filter(
        LogbookPersonConnection.owner == owner,
        LogbookPersonConnection.person_a_id == a_id,
        LogbookPersonConnection.person_b_id == b_id,
        LogbookPersonConnection.connection_type == normalized_type,
    ).first()
    duplicate = conn is not None
    if not conn:
        conn = LogbookPersonConnection(
            id=str(uuid.uuid4()),
            owner=owner,
            person_a_id=a_id,
            person_b_id=b_id,
            connection_type=normalized_type,
            description=None,
            strength=1,
            confidence=80,
            evidence_json="[]",
            status="accepted",
        )
        db.add(conn)
    _apply_connection_fields(
        conn,
        connection_type=normalized_type,
        description=description,
        strength=strength if strength is not None else conn.strength,
        confidence=confidence if confidence is not None else conn.confidence,
        status=status,
    )
    return conn, duplicate


def update_manual_connection(
    db,
    owner: str,
    conn: LogbookPersonConnection,
    *,
    connection_type: Optional[str] = None,
    description: Optional[str] = None,
    strength: Optional[int] = None,
    confidence: Optional[int] = None,
    status: Optional[str] = None,
    fields_set: Optional[set] = None,
) -> LogbookPersonConnection:
    fields = fields_set or set()
    if "connection_type" in fields:
        normalized_type = normalize_connection_type(connection_type, conn.connection_type or "unknown")
        if normalized_type != conn.connection_type:
            duplicate = db.query(LogbookPersonConnection.id).filter(
                LogbookPersonConnection.owner == owner,
                LogbookPersonConnection.person_a_id == conn.person_a_id,
                LogbookPersonConnection.person_b_id == conn.person_b_id,
                LogbookPersonConnection.connection_type == normalized_type,
                LogbookPersonConnection.id != conn.id,
            ).first()
            if duplicate:
                raise HTTPException(409, "A connection with this type already exists for these people")
            conn.connection_type = normalized_type
        fields = set(fields)
        fields.discard("connection_type")
    _apply_connection_fields(
        conn,
        description=description,
        strength=strength,
        confidence=confidence,
        status=status,
        fields_set=fields,
    )
    return conn


def sync_co_mentioned_connections(db, owner: str, entry: LogbookEntry, people: List[LogbookPerson]) -> None:
    unique_ids = sorted({p.id for p in people if p and p.id})
    if len(unique_ids) < 2:
        return
    snippet = entry_snippet(entry.content or "")
    for a_id, b_id in itertools.combinations(unique_ids, 2):
        upsert_co_mentioned_connection(db, owner, entry, a_id, b_id, snippet)


def _first_surface_offsets(content: str, surface_text: str) -> tuple[Optional[int], Optional[int]]:
    surface = str(surface_text or "").strip()
    if not content or not surface:
        return None, None
    index = content.lower().find(surface.lower())
    if index < 0:
        return None, None
    return index, index + len(surface)


def _entry_people(db, entry: LogbookEntry) -> List[LogbookPerson]:
    mentions = db.query(LogbookMention).options(selectinload(LogbookMention.person)).filter(
        LogbookMention.entry_id == entry.id,
    ).all()
    return [mention.person for mention in mentions if mention.person]


def link_person_suggestion(
    db,
    owner: str,
    entry: LogbookEntry,
    suggestion: Dict[str, Any],
    *,
    source: str = "ai",
) -> Optional[LogbookPerson]:
    if not isinstance(suggestion, dict):
        return None
    name = str(suggestion.get("display_name") or suggestion.get("surface_text") or "").strip()
    if not canonical_name(name):
        return None
    alias_values = suggestion.get("aliases") if isinstance(suggestion.get("aliases"), list) else None
    person = get_or_create_person(db, owner, name, alias_values)
    apply_person_suggestion_fields(db, owner, person, suggestion, entry=entry, source=source)
    exists = db.query(LogbookMention.id).filter(
        LogbookMention.entry_id == entry.id,
        LogbookMention.person_id == person.id,
    ).first()
    if exists:
        return person
    surface = str(suggestion.get("surface_text") or name).strip()
    start, end = _first_surface_offsets(entry.content or "", surface)
    db.add(LogbookMention(
        id=str(uuid.uuid4()),
        entry_id=entry.id,
        person_id=person.id,
        surface_text=surface,
        start_offset=start,
        end_offset=end,
        source=source,
        confidence=clamp_confidence(suggestion.get("confidence"), default=70),
    ))
    db.flush()
    sync_co_mentioned_connections(db, owner, entry, _entry_people(db, entry))
    return person


def link_location_suggestion(
    db,
    owner: str,
    entry: LogbookEntry,
    suggestion: Dict[str, Any],
    *,
    source: str = "ai",
) -> Optional[LogbookLocation]:
    if not isinstance(suggestion, dict):
        return None
    name = str(suggestion.get("display_name") or suggestion.get("surface_text") or "").strip()
    if not canonical_name(name):
        return None
    alias_values = suggestion.get("aliases") if isinstance(suggestion.get("aliases"), list) else None
    existing = find_location(db, owner, name, include_hidden=True)
    if location_is_hidden(existing):
        return None
    location = existing or get_or_create_location(db, owner, name, alias_values)
    exists = db.query(LogbookLocationMention.id).filter(
        LogbookLocationMention.entry_id == entry.id,
        LogbookLocationMention.location_id == location.id,
    ).first()
    if exists:
        return location
    surface = str(suggestion.get("surface_text") or name).strip()
    start, end = _first_surface_offsets(entry.content or "", surface)
    db.add(LogbookLocationMention(
        id=str(uuid.uuid4()),
        entry_id=entry.id,
        location_id=location.id,
        surface_text=surface,
        start_offset=start,
        end_offset=end,
        source=source,
        confidence=clamp_confidence(suggestion.get("confidence"), default=70),
    ))
    db.flush()
    return location


def rebuild_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookPerson]:
    db.query(LogbookMention).filter(LogbookMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    people_cache = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    mentioned_people: List[LogbookPerson] = []
    seen_mentions = set()
    blocked_ranges: List[tuple[int, int]] = []
    for parsed in parse_person_links(entry.content or ""):
        person = find_person(db, owner, parsed["target_name"], people_cache)
        if not person:
            person = find_person(db, owner, parsed["name"], people_cache)
        if not person:
            aliases_ = [parsed["name"]] if canonical_name(parsed["name"]) != parsed["target_name"] else None
            person = get_or_create_person(
                db,
                owner,
                parsed["target_display_name"] or parsed["name"],
                aliases_,
            )
            people_cache.append(person)
        elif canonical_name(parsed["name"]) != person.canonical_name:
            merge_aliases(person, [parsed["name"]])
        key = (person.id, parsed["start_offset"], parsed["end_offset"])
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
        db.add(LogbookMention(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            person_id=person.id,
            surface_text=parsed["surface_text"],
            start_offset=parsed["start_offset"],
            end_offset=parsed["end_offset"],
            source="mention",
            confidence=100,
        ))
        mentioned_people.append(person)
    for parsed in parse_mentions(entry.content or ""):
        if any(parsed["start_offset"] < end and parsed["end_offset"] > start for start, end in blocked_ranges):
            continue
        person = find_person(db, owner, parsed["name"], people_cache)
        if not person:
            person = get_or_create_person(db, owner, parsed["name"])
            people_cache.append(person)
        key = (person.id, parsed["start_offset"], parsed["end_offset"])
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        db.add(LogbookMention(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            person_id=person.id,
            surface_text=parsed["surface_text"],
            start_offset=parsed["start_offset"],
            end_offset=parsed["end_offset"],
            source="mention",
            confidence=100,
        ))
        mentioned_people.append(person)
        blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
    sync_co_mentioned_connections(db, owner, entry, mentioned_people)
    return mentioned_people


def rebuild_location_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookLocation]:
    db.query(LogbookLocationMention).filter(LogbookLocationMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    locations_cache = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    mentioned_locations: List[LogbookLocation] = []
    seen_mentions = set()
    blocked_ranges: List[tuple[int, int]] = []
    for parsed in parse_location_links(entry.content or ""):
        location = find_location(db, owner, parsed["target_name"], locations_cache, include_hidden=True)
        if not location:
            location = find_location(db, owner, parsed["name"], locations_cache, include_hidden=True)
        if location_is_hidden(location):
            blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
            continue
        if not location:
            aliases_ = [parsed["name"]] if canonical_name(parsed["name"]) != parsed["target_name"] else None
            location = get_or_create_location(
                db,
                owner,
                parsed["target_display_name"] or parsed["name"],
                aliases_,
            )
            locations_cache.append(location)
        elif canonical_name(parsed["name"]) != location.canonical_name:
            merge_location_aliases(location, [parsed["name"]])
        key = (location.id, parsed["start_offset"], parsed["end_offset"])
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
        db.add(LogbookLocationMention(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            location_id=location.id,
            surface_text=parsed["surface_text"],
            start_offset=parsed["start_offset"],
            end_offset=parsed["end_offset"],
            source="location",
            confidence=100,
        ))
        mentioned_locations.append(location)
    for parsed in parse_locations(entry.content or ""):
        if any(parsed["start_offset"] < end and parsed["end_offset"] > start for start, end in blocked_ranges):
            continue
        location = find_location(db, owner, parsed["name"], locations_cache, include_hidden=True)
        if location_is_hidden(location):
            blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
            continue
        if not location:
            location = get_or_create_location(db, owner, parsed["name"])
            locations_cache.append(location)
        key = (location.id, parsed["start_offset"], parsed["end_offset"])
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        db.add(LogbookLocationMention(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            location_id=location.id,
            surface_text=parsed["surface_text"],
            start_offset=parsed["start_offset"],
            end_offset=parsed["end_offset"],
            source="location",
            confidence=100,
        ))
        mentioned_locations.append(location)
        blocked_ranges.append((parsed["start_offset"], parsed["end_offset"]))
    return mentioned_locations


def rebuild_entry_links(db, owner: str, entry: LogbookEntry) -> None:
    rebuild_mentions(db, owner, entry)
    rebuild_location_mentions(db, owner, entry)


def apply_entry_fields(entry: LogbookEntry, body: BaseModel) -> bool:
    content_changed = False
    data = _model_data(body)
    if "title" in data:
        entry.title = normalized_title(data.get("title"))
    if "content" in data:
        entry.content = data.get("content") or ""
        content_changed = True
    if "summary" in data:
        entry.summary = data.get("summary")
    if "mood_label" in data:
        entry.mood_label = (data.get("mood_label") or "").strip() or None
    if "mood_score" in data:
        entry.mood_score = clamp_score(data.get("mood_score"))
    if "energy_score" in data:
        entry.energy_score = clamp_score(data.get("energy_score"))
    if "stress_score" in data:
        entry.stress_score = clamp_score(data.get("stress_score"))
    if "ai_reflection" in data:
        entry.ai_reflection = data.get("ai_reflection")
    return content_changed


def entry_query(db, owner: str):
    return db.query(LogbookEntry).options(
        selectinload(LogbookEntry.datapoints),
        selectinload(LogbookEntry.mentions).selectinload(LogbookMention.person),
        selectinload(LogbookEntry.location_mentions).selectinload(LogbookLocationMention.location),
    ).filter(LogbookEntry.owner == owner)


def load_entry_or_404(db, owner: str, entry_id: str) -> LogbookEntry:
    entry = entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Logbook entry not found")
    return entry


def person_query(db, owner: str):
    return db.query(LogbookPerson).filter(LogbookPerson.owner == owner)


def load_person_or_404(db, owner: str, person_id: str) -> LogbookPerson:
    person = person_query(db, owner).filter(LogbookPerson.id == person_id).first()
    if not person:
        raise HTTPException(404, "Person not found")
    return person


def location_query(db, owner: str, *, include_hidden: bool = False):
    query = db.query(LogbookLocation).filter(LogbookLocation.owner == owner)
    if not include_hidden:
        query = query.filter((LogbookLocation.hidden == False) | (LogbookLocation.hidden.is_(None)))
    return query


def load_location_or_404(db, owner: str, location_id: str, *, include_hidden: bool = True) -> LogbookLocation:
    location = location_query(db, owner, include_hidden=include_hidden).filter(LogbookLocation.id == location_id).first()
    if not location:
        raise HTTPException(404, "Location not found")
    return location


def entries_for_person(db, owner: str, person_id: str, *, limit: int = 20) -> List[LogbookEntry]:
    limit = max(1, min(int(limit or 20), 100))
    return (
        entry_query(db, owner)
        .join(LogbookMention, LogbookMention.entry_id == LogbookEntry.id)
        .filter(LogbookMention.person_id == person_id)
        .order_by(LogbookEntry.entry_date.desc(), LogbookEntry.updated_at.desc())
        .limit(limit)
        .all()
    )


def entries_for_location(db, owner: str, location_id: str, *, limit: int = 20) -> List[LogbookEntry]:
    limit = max(1, min(int(limit or 20), 100))
    return (
        entry_query(db, owner)
        .join(LogbookLocationMention, LogbookLocationMention.entry_id == LogbookEntry.id)
        .filter(LogbookLocationMention.location_id == location_id)
        .order_by(LogbookEntry.entry_date.desc(), LogbookEntry.updated_at.desc())
        .limit(limit)
        .all()
    )


def entries_for_people(db, owner: str, person_ids: List[str], *, limit: int = 20) -> List[LogbookEntry]:
    ids = [str(item) for item in person_ids or [] if item]
    if not ids:
        return []
    limit = max(1, min(int(limit or 20), 100))
    return (
        entry_query(db, owner)
        .join(LogbookMention, LogbookMention.entry_id == LogbookEntry.id)
        .filter(LogbookMention.person_id.in_(ids))
        .distinct()
        .order_by(LogbookEntry.entry_date.desc(), LogbookEntry.updated_at.desc())
        .limit(limit)
        .all()
    )


def connections_for_people(
    db,
    owner: str,
    person_ids: List[str],
    *,
    include_hidden: bool = False,
    limit_per_person: int = 6,
) -> Dict[str, List[LogbookPersonConnection]]:
    ids = sorted({str(item) for item in person_ids or [] if item})
    if not ids:
        return {}
    query = db.query(LogbookPersonConnection).options(
        selectinload(LogbookPersonConnection.person_a),
        selectinload(LogbookPersonConnection.person_b),
    ).filter(
        LogbookPersonConnection.owner == owner,
        or_(
            LogbookPersonConnection.person_a_id.in_(ids),
            LogbookPersonConnection.person_b_id.in_(ids),
        ),
    )
    if not include_hidden:
        query = query.filter(LogbookPersonConnection.status != "hidden")
    rows = query.order_by(LogbookPersonConnection.updated_at.desc()).all()
    grouped: Dict[str, List[LogbookPersonConnection]] = {person_id: [] for person_id in ids}
    for conn in rows:
        for person_id in (conn.person_a_id, conn.person_b_id):
            if person_id in grouped and len(grouped[person_id]) < limit_per_person:
                grouped[person_id].append(conn)
    return grouped


def load_connection_or_404(db, owner: str, connection_id: str) -> LogbookPersonConnection:
    conn = db.query(LogbookPersonConnection).options(
        selectinload(LogbookPersonConnection.person_a),
        selectinload(LogbookPersonConnection.person_b),
    ).filter(
        LogbookPersonConnection.owner == owner,
        LogbookPersonConnection.id == connection_id,
    ).first()
    if not conn:
        raise HTTPException(404, "Connection not found")
    return conn


def person_stats(db, owner: str) -> Dict[str, Dict[str, Any]]:
    rows = db.query(
        LogbookMention.person_id,
        func.count(LogbookMention.id),
        func.max(LogbookEntry.entry_date),
    ).join(LogbookEntry, LogbookMention.entry_id == LogbookEntry.id).filter(
        LogbookEntry.owner == owner,
    ).group_by(LogbookMention.person_id).all()
    return {
        person_id: {"mention_count": int(count or 0), "last_mentioned": last_date}
        for person_id, count, last_date in rows
    }


def location_stats(db, owner: str) -> Dict[str, Dict[str, Any]]:
    rows = db.query(
        LogbookLocationMention.location_id,
        func.count(LogbookLocationMention.id),
        func.max(LogbookEntry.entry_date),
    ).join(LogbookEntry, LogbookLocationMention.entry_id == LogbookEntry.id).filter(
        LogbookEntry.owner == owner,
    ).group_by(LogbookLocationMention.location_id).all()
    return {
        location_id: {"mention_count": int(count or 0), "last_mentioned": last_date}
        for location_id, count, last_date in rows
    }
