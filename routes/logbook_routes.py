"""Daily Logbook API."""

import itertools
import json
import re
import unicodedata
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy import func, or_
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


DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
MENTION_RE = re.compile(
    r"(?<![\w.])@(?:"
    r"\"(?P<quoted>[^\"\n]{1,80})\""
    r"|\[(?P<bracket>[^\]\n]{1,80})\]"
    r"|(?P<bare>[A-Za-z0-9À-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*"
    r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3})"
    r")"
)
LOCATION_RE = re.compile(
    r"(?<![\w#])#(?:"
    r"\"(?P<quoted>[^\"\n]{1,80})\""
    r"|\[(?P<bracket>[^\]\n]{1,80})\]"
    r"|(?P<bare>[A-Za-zÀ-ÖØ-öø-ÿ][A-Za-z0-9À-ÖØ-öø-ÿ_-]*"
    r"(?:\s+(?:[A-ZÀ-ÖØ-Þ][A-Za-z0-9À-ÖØ-öø-ÿ0-9_-]*|van|de|der|den|ten|ter|von|da|del|di|la|le|du)){0,3})"
    r")"
)

ALLOWED_CONNECTION_TYPES = {"co_mentioned", "family", "friend", "work", "training", "conflict", "unknown"}
ALLOWED_CONNECTION_STATUS = {"suggested", "accepted", "hidden"}
AI_MODES = {"clean_spelling", "structure_day", "summarize", "ask_questions", "extract_people", "extract_locations", "reflect", "extract_all"}


class LogbookDataPointIn(BaseModel):
    id: Optional[str] = None
    key: str = ""
    label: Optional[str] = None
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    unit: Optional[str] = None
    value_json: Optional[Any] = None
    sort_order: Optional[int] = None


class LogbookEntryUpsert(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    mood_label: Optional[str] = None
    mood_score: Optional[int] = None
    energy_score: Optional[int] = None
    stress_score: Optional[int] = None
    datapoints: Optional[List[LogbookDataPointIn]] = None


class LogbookEntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    mood_label: Optional[str] = None
    mood_score: Optional[int] = None
    energy_score: Optional[int] = None
    stress_score: Optional[int] = None
    ai_reflection: Optional[str] = None
    datapoints: Optional[List[LogbookDataPointIn]] = None


class LogbookPersonCreate(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None


class LogbookPersonUpdate(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None


class LogbookPeopleMerge(BaseModel):
    source_person_id: str
    target_person_id: str


class LogbookLocationCreate(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None


class LogbookLocationUpdate(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None


class LogbookLocationsMerge(BaseModel):
    source_location_id: str
    target_location_id: str


class LogbookAIAssist(BaseModel):
    entry_date: str
    content: str = ""
    mode: str
    locale: str = "en"
    current_entry: Optional[Dict[str, Any]] = None


def _owner(request: Request) -> str:
    require_user(request)
    return effective_user(request) or ""


def _validate_date(value: str) -> str:
    if not value or not DATE_RE.match(value):
        raise HTTPException(400, "Date must use YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date")
    return value


def _now_title(value: Optional[str]) -> str:
    title = (value or "").strip()
    return title or "Daily log"


def _json_load(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def _json_dump(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        try:
            json.loads(text)
            return text
        except json.JSONDecodeError:
            return json.dumps(text, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def _aliases(person: LogbookPerson) -> List[str]:
    raw = _json_load(person.aliases, [])
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def _canonical_name(name: str) -> str:
    value = (name or "").strip().strip("@").strip()
    value = value.strip("\"'[]")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s-]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"[_\s-]+", " ", value, flags=re.UNICODE)
    return value.strip().lower()


def _clean_key(value: str, fallback: str = "datapoint") -> str:
    key = _canonical_name(value).replace(" ", "_")
    key = re.sub(r"[^a-z0-9_]+", "", key)
    return key or fallback


def _clamp_score(value: Optional[int], *, low: int = 1, high: int = 5) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Score must be {low}..{high}")
    if n < low or n > high:
        raise HTTPException(400, f"Score must be {low}..{high}")
    return n


def _clamp_confidence(value: Any, default: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(0, min(100, n))


def _clamp_strength(value: Any, default: int = 1) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(1, min(5, n))


def _parse_mentions(content: str) -> List[Dict[str, Any]]:
    mentions: List[Dict[str, Any]] = []
    for match in MENTION_RE.finditer(content or ""):
        name = (match.group("quoted") or match.group("bracket") or match.group("bare") or "").strip()
        name = re.sub(r"\s+", " ", name)
        if not name:
            continue
        mentions.append({
            "name": name,
            "surface_text": match.group(0),
            "start_offset": match.start(),
            "end_offset": match.end(),
        })
    return mentions


def _parse_locations(content: str) -> List[Dict[str, Any]]:
    locations: List[Dict[str, Any]] = []
    for match in LOCATION_RE.finditer(content or ""):
        name = (match.group("quoted") or match.group("bracket") or match.group("bare") or "").strip()
        name = re.sub(r"\s+", " ", name)
        if not name:
            continue
        locations.append({
            "name": name,
            "surface_text": match.group(0),
            "start_offset": match.start(),
            "end_offset": match.end(),
        })
    return locations


def _person_to_dict(person: LogbookPerson) -> Dict[str, Any]:
    return {
        "id": person.id,
        "owner": person.owner,
        "display_name": person.display_name,
        "canonical_name": person.canonical_name,
        "aliases": _aliases(person),
        "notes": person.notes,
        "created_at": person.created_at.isoformat() if person.created_at else None,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
    }


def _location_to_dict(location: LogbookLocation) -> Dict[str, Any]:
    return {
        "id": location.id,
        "owner": location.owner,
        "display_name": location.display_name,
        "canonical_name": location.canonical_name,
        "aliases": _aliases(location),
        "notes": location.notes,
        "created_at": location.created_at.isoformat() if location.created_at else None,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,
    }


def _datapoint_to_dict(dp: LogbookDataPoint) -> Dict[str, Any]:
    return {
        "id": dp.id,
        "entry_id": dp.entry_id,
        "key": dp.key,
        "label": dp.label,
        "value_text": dp.value_text,
        "value_number": dp.value_number,
        "unit": dp.unit,
        "value_json": _json_load(dp.value_json, None),
        "sort_order": dp.sort_order or 0,
        "created_at": dp.created_at.isoformat() if dp.created_at else None,
        "updated_at": dp.updated_at.isoformat() if dp.updated_at else None,
    }


def _mention_to_dict(mention: LogbookMention) -> Dict[str, Any]:
    return {
        "id": mention.id,
        "entry_id": mention.entry_id,
        "person_id": mention.person_id,
        "surface_text": mention.surface_text,
        "start_offset": mention.start_offset,
        "end_offset": mention.end_offset,
        "source": mention.source,
        "confidence": mention.confidence,
        "created_at": mention.created_at.isoformat() if mention.created_at else None,
        "person": _person_to_dict(mention.person) if mention.person else None,
    }


def _location_mention_to_dict(mention: LogbookLocationMention) -> Dict[str, Any]:
    return {
        "id": mention.id,
        "entry_id": mention.entry_id,
        "location_id": mention.location_id,
        "surface_text": mention.surface_text,
        "start_offset": mention.start_offset,
        "end_offset": mention.end_offset,
        "source": mention.source,
        "confidence": mention.confidence,
        "created_at": mention.created_at.isoformat() if mention.created_at else None,
        "location": _location_to_dict(mention.location) if mention.location else None,
    }


def _connection_to_dict(conn: LogbookPersonConnection) -> Dict[str, Any]:
    evidence = _json_load(conn.evidence_json, [])
    return {
        "id": conn.id,
        "owner": conn.owner,
        "person_a_id": conn.person_a_id,
        "person_b_id": conn.person_b_id,
        "person_a": _person_to_dict(conn.person_a) if conn.person_a else None,
        "person_b": _person_to_dict(conn.person_b) if conn.person_b else None,
        "connection_type": conn.connection_type,
        "description": conn.description,
        "strength": conn.strength,
        "confidence": conn.confidence,
        "evidence": evidence if isinstance(evidence, list) else [],
        "status": conn.status,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


def _entry_to_dict(entry: LogbookEntry, *, full: bool = True) -> Dict[str, Any]:
    mentions = list(entry.mentions or [])
    location_mentions = list(entry.location_mentions or [])
    people_by_id: Dict[str, LogbookPerson] = {}
    for mention in mentions:
        if mention.person:
            people_by_id[mention.person.id] = mention.person
    locations_by_id: Dict[str, LogbookLocation] = {}
    for mention in location_mentions:
        if mention.location:
            locations_by_id[mention.location.id] = mention.location
    data = {
        "exists": True,
        "id": entry.id,
        "owner": entry.owner,
        "entry_date": entry.entry_date,
        "title": entry.title,
        "content": entry.content or "",
        "summary": entry.summary,
        "mood_label": entry.mood_label,
        "mood_score": entry.mood_score,
        "energy_score": entry.energy_score,
        "stress_score": entry.stress_score,
        "ai_reflection": entry.ai_reflection,
        "datapoint_count": len(entry.datapoints or []),
        "mention_count": len(mentions),
        "people_count": len(people_by_id),
        "location_mention_count": len(location_mentions),
        "location_count": len(locations_by_id),
        "created_at": entry.created_at.isoformat() if entry.created_at else None,
        "updated_at": entry.updated_at.isoformat() if entry.updated_at else None,
    }
    if full:
        data["datapoints"] = [_datapoint_to_dict(dp) for dp in (entry.datapoints or [])]
        data["mentions"] = [_mention_to_dict(m) for m in mentions]
        data["people"] = [_person_to_dict(p) for p in sorted(people_by_id.values(), key=lambda x: x.display_name.lower())]
        data["location_mentions"] = [_location_mention_to_dict(m) for m in location_mentions]
        data["locations"] = [_location_to_dict(l) for l in sorted(locations_by_id.values(), key=lambda x: x.display_name.lower())]
    return data


def _empty_entry_shape(entry_date: str) -> Dict[str, Any]:
    return {
        "exists": False,
        "entry_date": entry_date,
        "title": "Daily log",
        "content": "",
        "summary": None,
        "mood_label": None,
        "mood_score": None,
        "energy_score": None,
        "stress_score": None,
        "ai_reflection": None,
        "datapoints": [],
        "mentions": [],
        "people": [],
        "location_mentions": [],
        "locations": [],
    }


def _find_person(db, owner: str, name: str, people: Optional[List[LogbookPerson]] = None) -> Optional[LogbookPerson]:
    canonical = _canonical_name(name)
    if not canonical:
        return None
    candidates = people
    if candidates is None:
        candidates = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    for person in candidates:
        if person.canonical_name == canonical:
            return person
        for alias in _aliases(person):
            if _canonical_name(alias) == canonical:
                return person
    return None


def _merge_aliases(person: LogbookPerson, names: List[str]) -> None:
    existing = _aliases(person)
    seen = {_canonical_name(person.display_name), *[_canonical_name(a) for a in existing]}
    for name in names:
        label = str(name or "").strip()
        canonical = _canonical_name(label)
        if not label or not canonical or canonical in seen:
            continue
        existing.append(label)
        seen.add(canonical)
    person.aliases = json.dumps(existing, ensure_ascii=False) if existing else None


def _get_or_create_person(
    db,
    owner: str,
    display_name: str,
    aliases: Optional[List[str]] = None,
    notes: Optional[str] = None,
    *,
    update_existing: bool = False,
) -> LogbookPerson:
    name = re.sub(r"\s+", " ", (display_name or "").strip())
    canonical = _canonical_name(name)
    if not canonical:
        raise HTTPException(400, "display_name is required")
    person = _find_person(db, owner, name)
    if person:
        if update_existing:
            person.display_name = name
            person.canonical_name = canonical
            person.notes = notes
        if aliases:
            _merge_aliases(person, aliases)
        db.flush()
        return person
    person = LogbookPerson(
        id=str(uuid.uuid4()),
        owner=owner,
        display_name=name,
        canonical_name=canonical,
        aliases=json.dumps([a for a in (aliases or []) if str(a).strip()], ensure_ascii=False) if aliases else None,
        notes=notes,
    )
    db.add(person)
    db.flush()
    return person


def _find_location(db, owner: str, name: str, locations: Optional[List[LogbookLocation]] = None) -> Optional[LogbookLocation]:
    canonical = _canonical_name(name)
    if not canonical:
        return None
    candidates = locations
    if candidates is None:
        candidates = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    for location in candidates:
        if location.canonical_name == canonical:
            return location
        for alias in _aliases(location):
            if _canonical_name(alias) == canonical:
                return location
    return None


def _merge_location_aliases(location: LogbookLocation, names: List[str]) -> None:
    existing = _aliases(location)
    seen = {_canonical_name(location.display_name), *[_canonical_name(a) for a in existing]}
    for name in names:
        label = str(name or "").strip()
        canonical = _canonical_name(label)
        if not label or not canonical or canonical in seen:
            continue
        existing.append(label)
        seen.add(canonical)
    location.aliases = json.dumps(existing, ensure_ascii=False) if existing else None


def _get_or_create_location(
    db,
    owner: str,
    display_name: str,
    aliases: Optional[List[str]] = None,
    notes: Optional[str] = None,
    *,
    update_existing: bool = False,
) -> LogbookLocation:
    name = re.sub(r"\s+", " ", (display_name or "").strip())
    canonical = _canonical_name(name)
    if not canonical:
        raise HTTPException(400, "display_name is required")
    location = _find_location(db, owner, name)
    if location:
        if update_existing:
            location.display_name = name
            location.canonical_name = canonical
            location.notes = notes
        if aliases:
            _merge_location_aliases(location, aliases)
        db.flush()
        return location
    location = LogbookLocation(
        id=str(uuid.uuid4()),
        owner=owner,
        display_name=name,
        canonical_name=canonical,
        aliases=json.dumps([a for a in (aliases or []) if str(a).strip()], ensure_ascii=False) if aliases else None,
        notes=notes,
    )
    db.add(location)
    db.flush()
    return location


def _replace_datapoints(db, entry: LogbookEntry, datapoints: List[LogbookDataPointIn]) -> None:
    db.query(LogbookDataPoint).filter(LogbookDataPoint.entry_id == entry.id).delete(synchronize_session=False)
    for index, item in enumerate(datapoints or []):
        label = (item.label or "").strip() or None
        key = _clean_key(item.key or label or "datapoint")
        db.add(LogbookDataPoint(
            id=str(uuid.uuid4()),
            entry_id=entry.id,
            key=key,
            label=label,
            value_text=item.value_text,
            value_number=item.value_number,
            unit=(item.unit or "").strip() or None,
            value_json=_json_dump(item.value_json),
            sort_order=item.sort_order if item.sort_order is not None else index,
        ))


def _entry_snippet(content: str, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _pair_ids(person_a_id: str, person_b_id: str) -> Optional[tuple]:
    if not person_a_id or not person_b_id or person_a_id == person_b_id:
        return None
    return tuple(sorted([person_a_id, person_b_id]))


def _add_evidence(existing: List[Dict[str, Any]], entry: LogbookEntry, snippet: str, source: str = "logbook") -> List[Dict[str, Any]]:
    evidence = [e for e in existing if isinstance(e, dict)]
    if not any(e.get("entry_id") == entry.id and e.get("source", "logbook") == source for e in evidence):
        evidence.append({
            "entry_id": entry.id,
            "entry_date": entry.entry_date,
            "snippet": snippet,
            "source": source,
        })
    return evidence[-8:]


def _upsert_co_mentioned_connection(db, owner: str, entry: LogbookEntry, person_a_id: str, person_b_id: str, snippet: str) -> None:
    pair = _pair_ids(person_a_id, person_b_id)
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
    evidence = _add_evidence(_json_load(conn.evidence_json, []), entry, snippet)
    count = len(evidence)
    conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
    conn.strength = max(conn.strength or 1, min(5, 1 + max(0, count - 1) // 2))
    conn.confidence = max(conn.confidence or 0, min(90, 55 + count * 8))
    if conn.status not in ALLOWED_CONNECTION_STATUS:
        conn.status = "suggested"


def _sync_co_mentioned_connections(db, owner: str, entry: LogbookEntry, people: List[LogbookPerson]) -> None:
    unique_ids = sorted({p.id for p in people if p and p.id})
    if len(unique_ids) < 2:
        return
    snippet = _entry_snippet(entry.content or "")
    for a_id, b_id in itertools.combinations(unique_ids, 2):
        _upsert_co_mentioned_connection(db, owner, entry, a_id, b_id, snippet)


def _rebuild_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookPerson]:
    db.query(LogbookMention).filter(LogbookMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    people_cache = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    mentioned_people: List[LogbookPerson] = []
    seen_mentions = set()
    for parsed in _parse_mentions(entry.content or ""):
        person = _find_person(db, owner, parsed["name"], people_cache)
        if not person:
            person = _get_or_create_person(db, owner, parsed["name"])
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
    _sync_co_mentioned_connections(db, owner, entry, mentioned_people)
    return mentioned_people


def _rebuild_location_mentions(db, owner: str, entry: LogbookEntry) -> List[LogbookLocation]:
    db.query(LogbookLocationMention).filter(LogbookLocationMention.entry_id == entry.id).delete(synchronize_session=False)
    db.flush()
    locations_cache = db.query(LogbookLocation).filter(LogbookLocation.owner == owner).all()
    mentioned_locations: List[LogbookLocation] = []
    seen_mentions = set()
    for parsed in _parse_locations(entry.content or ""):
        location = _find_location(db, owner, parsed["name"], locations_cache)
        if not location:
            location = _get_or_create_location(db, owner, parsed["name"])
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


def _rebuild_entry_links(db, owner: str, entry: LogbookEntry) -> None:
    _rebuild_mentions(db, owner, entry)
    _rebuild_location_mentions(db, owner, entry)


def _apply_entry_fields(entry: LogbookEntry, body: BaseModel) -> bool:
    content_changed = False
    data = body.dict(exclude_unset=True)
    if "title" in data:
        entry.title = _now_title(data.get("title"))
    if "content" in data:
        entry.content = data.get("content") or ""
        content_changed = True
    if "summary" in data:
        entry.summary = data.get("summary")
    if "mood_label" in data:
        entry.mood_label = (data.get("mood_label") or "").strip() or None
    if "mood_score" in data:
        entry.mood_score = _clamp_score(data.get("mood_score"))
    if "energy_score" in data:
        entry.energy_score = _clamp_score(data.get("energy_score"))
    if "stress_score" in data:
        entry.stress_score = _clamp_score(data.get("stress_score"))
    if "ai_reflection" in data:
        entry.ai_reflection = data.get("ai_reflection")
    return content_changed


def _entry_query(db, owner: str):
    return db.query(LogbookEntry).options(
        selectinload(LogbookEntry.datapoints),
        selectinload(LogbookEntry.mentions).selectinload(LogbookMention.person),
        selectinload(LogbookEntry.location_mentions).selectinload(LogbookLocationMention.location),
    ).filter(LogbookEntry.owner == owner)


def _load_entry_or_404(db, owner: str, entry_id: str) -> LogbookEntry:
    entry = _entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
    if not entry:
        raise HTTPException(404, "Logbook entry not found")
    return entry


def _person_query(db, owner: str):
    return db.query(LogbookPerson).filter(LogbookPerson.owner == owner)


def _load_person_or_404(db, owner: str, person_id: str) -> LogbookPerson:
    person = _person_query(db, owner).filter(LogbookPerson.id == person_id).first()
    if not person:
        raise HTTPException(404, "Person not found")
    return person


def _location_query(db, owner: str):
    return db.query(LogbookLocation).filter(LogbookLocation.owner == owner)


def _load_location_or_404(db, owner: str, location_id: str) -> LogbookLocation:
    location = _location_query(db, owner).filter(LogbookLocation.id == location_id).first()
    if not location:
        raise HTTPException(404, "Location not found")
    return location


def _load_connection_or_404(db, owner: str, connection_id: str) -> LogbookPersonConnection:
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


def _person_stats(db, owner: str) -> Dict[str, Dict[str, Any]]:
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


def _location_stats(db, owner: str) -> Dict[str, Dict[str, Any]]:
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


def _with_stats(data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    data.update({
        "mention_count": int(stats.get("mention_count") or 0),
        "last_mentioned": stats.get("last_mentioned"),
    })
    return data


def _extract_json_object(text: str) -> Dict[str, Any]:
    if not text:
        return {}
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        obj = json.loads(cleaned)
        return obj if isinstance(obj, dict) else {}
    except json.JSONDecodeError:
        pass
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start >= 0 and end > start:
        try:
            obj = json.loads(cleaned[start:end + 1])
            return obj if isinstance(obj, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _deterministic_ai_suggestions(content: str) -> Dict[str, Any]:
    people = []
    seen = set()
    for mention in _parse_mentions(content or ""):
        canonical = _canonical_name(mention["name"])
        if canonical in seen:
            continue
        seen.add(canonical)
        people.append({
            "display_name": mention["name"],
            "surface_text": mention["surface_text"],
            "confidence": 95,
            "reason": "Explicit @mention",
        })
    connections = []
    for a, b in itertools.combinations(people, 2):
        connections.append({
            "person_a": a["display_name"],
            "person_b": b["display_name"],
            "connection_type": "co_mentioned",
            "description": "Mentioned together in this entry",
            "confidence": 65,
            "evidence": _entry_snippet(content),
        })
    locations = []
    seen_locations = set()
    for mention in _parse_locations(content or ""):
        canonical = _canonical_name(mention["name"])
        if canonical in seen_locations:
            continue
        seen_locations.add(canonical)
        locations.append({
            "display_name": mention["name"],
            "surface_text": mention["surface_text"],
            "confidence": 95,
            "reason": "Explicit #location",
        })
    return {
        "people_suggestions": people,
        "location_suggestions": locations,
        "connection_suggestions": connections,
    }


def _normalize_ai_payload(mode: str, raw: Dict[str, Any], content: str) -> Dict[str, Any]:
    out = {
        "ok": True,
        "mode": mode,
        "preview_content": raw.get("preview_content"),
        "summary": raw.get("summary"),
        "questions": raw.get("questions") if isinstance(raw.get("questions"), list) else [],
        "mood_suggestion": raw.get("mood_suggestion") if isinstance(raw.get("mood_suggestion"), dict) else None,
        "datapoint_suggestions": raw.get("datapoint_suggestions") if isinstance(raw.get("datapoint_suggestions"), list) else [],
        "people_suggestions": raw.get("people_suggestions") if isinstance(raw.get("people_suggestions"), list) else [],
        "location_suggestions": raw.get("location_suggestions") if isinstance(raw.get("location_suggestions"), list) else [],
        "connection_suggestions": raw.get("connection_suggestions") if isinstance(raw.get("connection_suggestions"), list) else [],
        "reflection": raw.get("reflection"),
    }
    if mode in {"clean_spelling", "structure_day"} and not out["preview_content"]:
        out["preview_content"] = raw.get("content") or content
    if mode == "summarize" and not out["summary"]:
        out["summary"] = raw.get("preview_content") or raw.get("content")
    if mode == "reflect" and not out["reflection"]:
        out["reflection"] = raw.get("preview_content") or raw.get("summary")
    out["questions"] = [str(q).strip() for q in out["questions"] if str(q).strip()][:3]
    deterministic = _deterministic_ai_suggestions(content)
    seen_people = {_canonical_name(p.get("display_name", "")) for p in out["people_suggestions"] if isinstance(p, dict)}
    for person in deterministic["people_suggestions"]:
        if _canonical_name(person["display_name"]) not in seen_people:
            out["people_suggestions"].append(person)
    seen_locations = {_canonical_name(l.get("display_name", "")) for l in out["location_suggestions"] if isinstance(l, dict)}
    for location in deterministic["location_suggestions"]:
        if _canonical_name(location["display_name"]) not in seen_locations:
            out["location_suggestions"].append(location)
    if not out["connection_suggestions"]:
        out["connection_suggestions"] = deterministic["connection_suggestions"]
    return out


def _ai_system_prompt(mode: str, locale: str) -> str:
    return (
        "You help with dyslexia-friendly daily journaling. Preserve the user's meaning, tone, and voice. "
        "Use simple wording, short paragraphs, and bullets when helpful. Do not mention dyslexia unless the user does. "
        "Never shame the user. For clean_spelling, change as little as possible. "
        "For structure_day, turn messy notes into a readable daily log without inventing facts. "
        "For ask_questions, ask at most three short questions that can be answered in a few words. "
        "For reflect, give a gentle reflection, not therapy or medical advice. "
        "For people, locations, and connections, use only evidence from the supplied logbook text. "
        "Locations are places such as home, gym, office, city, route, venue, or clinic. "
        "Connections are possible suggestions, not facts, unless the user accepts them. "
        f"Locale: {locale}. Mode: {mode}. "
        "Return strict JSON only with keys: ok, mode, preview_content, summary, questions, mood_suggestion, "
        "datapoint_suggestions, people_suggestions, location_suggestions, connection_suggestions, reflection. "
        "connection_suggestions items must include person_a, person_b, connection_type, description, confidence, evidence."
    )


async def _run_ai_assist(owner: str, payload: LogbookAIAssist) -> JSONResponse | Dict[str, Any]:
    mode = (payload.mode or "").strip()
    if mode not in AI_MODES:
        raise HTTPException(400, "Unknown AI assist mode")
    entry_date = _validate_date(payload.entry_date)
    locale = payload.locale if payload.locale in {"en", "nl"} else "en"
    try:
        from src.endpoint_resolver import resolve_endpoint
        from src.llm_core import llm_call_async
        from src.text_helpers import strip_think
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "error": "AI helpers are unavailable"})

    url, model, headers = resolve_endpoint("utility", owner=owner)
    if not url or not model:
        url, model, headers = resolve_endpoint("default", owner=owner)
    if not url or not model:
        return JSONResponse(status_code=503, content={"ok": False, "error": "No utility or default model is configured"})

    current_entry = payload.current_entry or {}
    messages = [
        {"role": "system", "content": _ai_system_prompt(mode, locale)},
        {
            "role": "user",
            "content": json.dumps({
                "entry_date": entry_date,
                "mode": mode,
                "content": payload.content or "",
                "current_entry": current_entry,
            }, ensure_ascii=False),
        },
    ]
    try:
        raw = await llm_call_async(
            url=url,
            model=model,
            messages=messages,
            temperature=0.2 if mode in {"extract_people", "extract_all", "summarize"} else 0.4,
            max_tokens=1600,
            headers=headers,
            timeout=45,
            owner=owner,
        )
    except HTTPException as exc:
        return JSONResponse(status_code=exc.status_code, content={"ok": False, "error": str(exc.detail)})
    except Exception:
        return JSONResponse(status_code=503, content={"ok": False, "error": "AI assist failed. Your entry was not changed."})
    cleaned = strip_think(raw or "", prose=True, prompt_echo=True)
    parsed = _extract_json_object(cleaned)
    return _normalize_ai_payload(mode, parsed, payload.content or "")


def _store_ai_connection_suggestions(
    db,
    owner: str,
    entry: LogbookEntry,
    suggestions: List[Dict[str, Any]],
) -> List[LogbookPersonConnection]:
    people = db.query(LogbookPerson).filter(LogbookPerson.owner == owner).all()
    created_or_updated: List[LogbookPersonConnection] = []
    for suggestion in suggestions or []:
        if not isinstance(suggestion, dict):
            continue
        confidence = _clamp_confidence(suggestion.get("confidence"))
        if confidence < 50:
            continue
        person_a = _find_person(db, owner, str(suggestion.get("person_a") or ""), people)
        person_b = _find_person(db, owner, str(suggestion.get("person_b") or ""), people)
        if not person_a or not person_b:
            continue
        pair = _pair_ids(person_a.id, person_b.id)
        if not pair:
            continue
        a_id, b_id = pair
        ctype = str(suggestion.get("connection_type") or "unknown").strip().lower()
        if ctype not in ALLOWED_CONNECTION_TYPES:
            ctype = "unknown"
        evidence_text = _entry_snippet(str(suggestion.get("evidence") or suggestion.get("description") or entry.content or ""))
        conn = db.query(LogbookPersonConnection).filter(
            LogbookPersonConnection.owner == owner,
            LogbookPersonConnection.person_a_id == a_id,
            LogbookPersonConnection.person_b_id == b_id,
            LogbookPersonConnection.connection_type == ctype,
        ).first()
        if not conn:
            conn = LogbookPersonConnection(
                id=str(uuid.uuid4()),
                owner=owner,
                person_a_id=a_id,
                person_b_id=b_id,
                connection_type=ctype,
                description=str(suggestion.get("description") or "").strip() or None,
                strength=1 if confidence < 75 else 2,
                confidence=confidence,
                evidence_json="[]",
                status="suggested",
            )
            db.add(conn)
        elif conn.status == "accepted" and confidence <= (conn.confidence or 0):
            evidence = _add_evidence(_json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
            conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
            created_or_updated.append(conn)
            continue
        elif conn.status == "hidden":
            evidence = _add_evidence(_json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
            conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
            created_or_updated.append(conn)
            continue
        conn.description = str(suggestion.get("description") or conn.description or "").strip() or None
        conn.confidence = max(conn.confidence or 0, confidence)
        conn.strength = max(conn.strength or 1, 1 if confidence < 75 else 2)
        evidence = _add_evidence(_json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
        conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
        created_or_updated.append(conn)
    return created_or_updated


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
            start = _validate_date(start)
        if end:
            end = _validate_date(end)
        db = SessionLocal()
        try:
            query = _entry_query(db, owner)
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
                query = query.join(LogbookDataPoint, LogbookDataPoint.entry_id == LogbookEntry.id).filter(LogbookDataPoint.key == _clean_key(datapoint_key))
            if person_id or location_id or datapoint_key:
                query = query.distinct()
            entries = query.order_by(LogbookEntry.entry_date.desc(), LogbookEntry.updated_at.desc()).all()
            return {"entries": [_entry_to_dict(entry, full=False) for entry in entries]}
        finally:
            db.close()

    @router.get("/entry/{entry_date}")
    def get_entry_by_date(request: Request, entry_date: str):
        owner = _owner(request)
        entry_date = _validate_date(entry_date)
        db = SessionLocal()
        try:
            entry = _entry_query(db, owner).filter(LogbookEntry.entry_date == entry_date).first()
            if not entry:
                return _empty_entry_shape(entry_date)
            return _entry_to_dict(entry)
        finally:
            db.close()

    @router.post("/entry/{entry_date}")
    def upsert_entry_by_date(request: Request, entry_date: str, body: LogbookEntryUpsert):
        owner = _owner(request)
        entry_date = _validate_date(entry_date)
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
                    title=_now_title(body.title),
                    content=body.content or "",
                )
                db.add(entry)
                db.flush()
            content_changed = _apply_entry_fields(entry, body)
            if body.datapoints is not None:
                _replace_datapoints(db, entry, body.datapoints)
            if content_changed or not entry.mentions or not entry.location_mentions:
                _rebuild_entry_links(db, owner, entry)
            db.commit()
            entry = _entry_query(db, owner).filter(LogbookEntry.id == entry.id).first()
            return _entry_to_dict(entry)
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
            entry = _load_entry_or_404(db, owner, entry_id)
            content_changed = _apply_entry_fields(entry, body)
            if body.datapoints is not None:
                _replace_datapoints(db, entry, body.datapoints)
            if content_changed:
                _rebuild_entry_links(db, owner, entry)
            db.commit()
            entry = _entry_query(db, owner).filter(LogbookEntry.id == entry_id).first()
            return _entry_to_dict(entry)
        finally:
            db.close()

    @router.delete("/entry/{entry_id}")
    def delete_entry(request: Request, entry_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = _load_entry_or_404(db, owner, entry_id)
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
            people = _person_query(db, owner).all()
            stats = _person_stats(db, owner)
            term = _canonical_name(q or "")
            if term:
                people = [
                    p for p in people
                    if term in p.canonical_name or any(term in _canonical_name(a) for a in _aliases(p))
                ]
            def score(person: LogbookPerson):
                if not term:
                    return (1, person.display_name.lower())
                aliases = [_canonical_name(a) for a in _aliases(person)]
                exact = person.canonical_name == term or term in aliases
                prefix = person.canonical_name.startswith(term) or any(a.startswith(term) for a in aliases)
                return (0 if exact else 1 if prefix else 2, person.display_name.lower())
            people.sort(key=score)
            return {"people": [_with_stats(_person_to_dict(p), stats.get(p.id, {})) for p in people]}
        finally:
            db.close()

    @router.post("/people")
    def create_person(request: Request, body: LogbookPersonCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            existing = _find_person(db, owner, body.display_name)
            person = _get_or_create_person(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "person": _person_to_dict(person)}
        finally:
            db.close()

    @router.put("/people/{person_id}")
    def update_person(request: Request, person_id: str, body: LogbookPersonUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            person = _load_person_or_404(db, owner, person_id)
            if body.display_name is not None:
                canonical = _canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                duplicate = _person_query(db, owner).filter(
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
            return {"ok": True, "person": _person_to_dict(person)}
        finally:
            db.close()

    @router.post("/people/merge")
    def merge_people(request: Request, body: LogbookPeopleMerge):
        owner = _owner(request)
        if body.source_person_id == body.target_person_id:
            raise HTTPException(400, "Choose two different people")
        db = SessionLocal()
        try:
            source = _load_person_or_404(db, owner, body.source_person_id)
            target = _load_person_or_404(db, owner, body.target_person_id)
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
                pair = _pair_ids(target.id, other_id)
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
                    evidence = _json_load(existing.evidence_json, []) + _json_load(conn.evidence_json, [])
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
            _merge_aliases(target, [source.display_name] + _aliases(source))
            db.delete(source)
            db.commit()
            return {"ok": True, "person": _person_to_dict(target)}
        finally:
            db.close()

    @router.get("/locations")
    def list_locations(request: Request, q: Optional[str] = None):
        owner = _owner(request)
        db = SessionLocal()
        try:
            locations = _location_query(db, owner).all()
            stats = _location_stats(db, owner)
            term = _canonical_name(q or "")
            if term:
                locations = [
                    loc for loc in locations
                    if term in loc.canonical_name or any(term in _canonical_name(a) for a in _aliases(loc))
                ]
            def score(location: LogbookLocation):
                if not term:
                    return (1, location.display_name.lower())
                aliases = [_canonical_name(a) for a in _aliases(location)]
                exact = location.canonical_name == term or term in aliases
                prefix = location.canonical_name.startswith(term) or any(a.startswith(term) for a in aliases)
                return (0 if exact else 1 if prefix else 2, location.display_name.lower())
            locations.sort(key=score)
            return {"locations": [_with_stats(_location_to_dict(loc), stats.get(loc.id, {})) for loc in locations]}
        finally:
            db.close()

    @router.post("/locations")
    def create_location(request: Request, body: LogbookLocationCreate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            existing = _find_location(db, owner, body.display_name)
            location = _get_or_create_location(db, owner, body.display_name, body.aliases, body.notes, update_existing=not existing)
            db.commit()
            return {"ok": True, "duplicate": bool(existing), "location": _location_to_dict(location)}
        finally:
            db.close()

    @router.put("/locations/{location_id}")
    def update_location(request: Request, location_id: str, body: LogbookLocationUpdate):
        owner = _owner(request)
        db = SessionLocal()
        try:
            location = _load_location_or_404(db, owner, location_id)
            if body.display_name is not None:
                canonical = _canonical_name(body.display_name)
                if not canonical:
                    raise HTTPException(400, "display_name is required")
                duplicate = _location_query(db, owner).filter(
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
            return {"ok": True, "location": _location_to_dict(location)}
        finally:
            db.close()

    @router.post("/locations/merge")
    def merge_locations(request: Request, body: LogbookLocationsMerge):
        owner = _owner(request)
        if body.source_location_id == body.target_location_id:
            raise HTTPException(400, "Choose two different locations")
        db = SessionLocal()
        try:
            source = _load_location_or_404(db, owner, body.source_location_id)
            target = _load_location_or_404(db, owner, body.target_location_id)
            db.query(LogbookLocationMention).filter(LogbookLocationMention.location_id == source.id).update(
                {LogbookLocationMention.location_id: target.id},
                synchronize_session=False,
            )
            _merge_location_aliases(target, [source.display_name] + _aliases(source))
            db.delete(source)
            db.commit()
            return {"ok": True, "location": _location_to_dict(target)}
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
            return {"connections": [_connection_to_dict(conn) for conn in conns]}
        finally:
            db.close()

    @router.post("/connections/{connection_id}/accept")
    def accept_connection(request: Request, connection_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn = _load_connection_or_404(db, owner, connection_id)
            conn.status = "accepted"
            db.commit()
            return {"ok": True, "connection": _connection_to_dict(conn)}
        finally:
            db.close()

    @router.post("/connections/{connection_id}/hide")
    def hide_connection(request: Request, connection_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            conn = _load_connection_or_404(db, owner, connection_id)
            conn.status = "hidden"
            db.commit()
            return {"ok": True, "connection": _connection_to_dict(conn)}
        finally:
            db.close()

    @router.post("/ai/assist")
    async def ai_assist(request: Request, body: LogbookAIAssist):
        owner = _owner(request)
        return await _run_ai_assist(owner, body)

    @router.post("/ai/analyze-entry/{entry_id}")
    async def analyze_entry(request: Request, entry_id: str):
        owner = _owner(request)
        db = SessionLocal()
        try:
            entry = _load_entry_or_404(db, owner, entry_id)
            payload = LogbookAIAssist(
                entry_date=entry.entry_date,
                content=entry.content or "",
                mode="extract_all",
                locale="en",
                current_entry=_entry_to_dict(entry),
            )
            result = await _run_ai_assist(owner, payload)
            if isinstance(result, JSONResponse):
                return result
            stored = _store_ai_connection_suggestions(db, owner, entry, result.get("connection_suggestions") or [])
            db.commit()
            result["stored_connections"] = [_connection_to_dict(c) for c in stored]
            return result
        finally:
            db.close()

    return router
