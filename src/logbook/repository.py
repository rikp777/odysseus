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
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
    LogbookPerson,
    LogbookPersonConnection,
)
from src.logbook.schemas import ALLOWED_CONNECTION_STATUS, LogbookDataPointIn
from src.logbook.utils import (
    add_evidence,
    aliases,
    canonical_name,
    clamp_score,
    clean_key,
    entry_snippet,
    json_dump,
    json_load,
    normalized_title,
    pair_ids,
    parse_locations,
    parse_mentions,
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


def find_location(db, owner: str, name: str, locations: Optional[List[LogbookLocation]] = None) -> Optional[LogbookLocation]:
    canonical = canonical_name(name)
    if not canonical:
        return None
    candidates = locations
    if candidates is None:
        candidates = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    for location in candidates:
        if location.canonical_name == canonical:
            return location
        for alias in aliases(location):
            if canonical_name(alias) == canonical:
                return location
    return None


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
) -> LogbookLocation:
    name = re.sub(r"\s+", " ", (display_name or "").strip())
    canonical = canonical_name(name)
    if not canonical:
        raise HTTPException(400, "display_name is required")
    location = find_location(db, owner, name)
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


def sync_co_mentioned_connections(db, owner: str, entry: LogbookEntry, people: List[LogbookPerson]) -> None:
    unique_ids = sorted({p.id for p in people if p and p.id})
    if len(unique_ids) < 2:
        return
    snippet = entry_snippet(entry.content or "")
    for a_id, b_id in itertools.combinations(unique_ids, 2):
        upsert_co_mentioned_connection(db, owner, entry, a_id, b_id, snippet)


def rebuild_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookPerson]:
    db.query(LogbookMention).filter(LogbookMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    people_cache = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    mentioned_people: List[LogbookPerson] = []
    seen_mentions = set()
    for parsed in parse_mentions(entry.content or ""):
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
    sync_co_mentioned_connections(db, owner, entry, mentioned_people)
    return mentioned_people


def rebuild_location_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookLocation]:
    db.query(LogbookLocationMention).filter(LogbookLocationMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    locations_cache = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    mentioned_locations: List[LogbookLocation] = []
    seen_mentions = set()
    for parsed in parse_locations(entry.content or ""):
        location = find_location(db, owner, parsed["name"], locations_cache)
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
    return mentioned_locations


def rebuild_entry_links(db, owner: str, entry: LogbookEntry) -> None:
    rebuild_mentions(db, owner, entry)
    rebuild_location_mentions(db, owner, entry)


def apply_entry_fields(entry: LogbookEntry, body: BaseModel) -> bool:
    content_changed = False
    data = body.dict(exclude_unset=True)
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


def location_query(db, owner: str):
    return db.query(LogbookLocation).filter(LogbookLocation.owner == owner)


def load_location_or_404(db, owner: str, location_id: str) -> LogbookLocation:
    location = location_query(db, owner).filter(LogbookLocation.id == location_id).first()
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
