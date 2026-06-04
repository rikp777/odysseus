"""Daily Logbook response serializers."""

from __future__ import annotations

from typing import Any, Dict

from core.database import (
    LogbookDataPoint,
    LogbookEntry,
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
    LogbookPerson,
    LogbookPersonConnection,
)
from src.logbook.utils import aliases, json_load


def person_to_dict(person: LogbookPerson) -> Dict[str, Any]:
    contact_snapshot = json_load(getattr(person, "contact_snapshot_json", None), None)
    return {
        "id": person.id,
        "owner": person.owner,
        "display_name": person.display_name,
        "canonical_name": person.canonical_name,
        "aliases": aliases(person),
        "notes": person.notes,
        "relationship_label": getattr(person, "relationship_label", None),
        "llm_context": getattr(person, "llm_context", None),
        "contact_uid": getattr(person, "contact_uid", None),
        "contact_source": getattr(person, "contact_source", None),
        "contact_snapshot": contact_snapshot if isinstance(contact_snapshot, dict) else None,
        "created_at": person.created_at.isoformat() if person.created_at else None,
        "updated_at": person.updated_at.isoformat() if person.updated_at else None,
    }


def location_to_dict(location: LogbookLocation) -> Dict[str, Any]:
    return {
        "id": location.id,
        "owner": location.owner,
        "display_name": location.display_name,
        "canonical_name": location.canonical_name,
        "aliases": aliases(location),
        "notes": location.notes,
        "address": getattr(location, "address", None),
        "latitude": getattr(location, "latitude", None),
        "longitude": getattr(location, "longitude", None),
        "location_type": getattr(location, "location_type", None),
        "llm_context": getattr(location, "llm_context", None),
        "created_at": location.created_at.isoformat() if location.created_at else None,
        "updated_at": location.updated_at.isoformat() if location.updated_at else None,
    }


def datapoint_to_dict(dp: LogbookDataPoint) -> Dict[str, Any]:
    return {
        "id": dp.id,
        "entry_id": dp.entry_id,
        "key": dp.key,
        "label": dp.label,
        "value_text": dp.value_text,
        "value_number": dp.value_number,
        "unit": dp.unit,
        "value_json": json_load(dp.value_json, None),
        "sort_order": dp.sort_order or 0,
        "created_at": dp.created_at.isoformat() if dp.created_at else None,
        "updated_at": dp.updated_at.isoformat() if dp.updated_at else None,
    }


def mention_to_dict(mention: LogbookMention) -> Dict[str, Any]:
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
        "person": person_to_dict(mention.person) if mention.person else None,
    }


def location_mention_to_dict(mention: LogbookLocationMention) -> Dict[str, Any]:
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
        "location": location_to_dict(mention.location) if mention.location else None,
    }


def connection_to_dict(conn: LogbookPersonConnection) -> Dict[str, Any]:
    evidence = json_load(conn.evidence_json, [])
    return {
        "id": conn.id,
        "owner": conn.owner,
        "person_a_id": conn.person_a_id,
        "person_b_id": conn.person_b_id,
        "person_a": person_to_dict(conn.person_a) if conn.person_a else None,
        "person_b": person_to_dict(conn.person_b) if conn.person_b else None,
        "connection_type": conn.connection_type,
        "description": conn.description,
        "strength": conn.strength,
        "confidence": conn.confidence,
        "evidence": evidence if isinstance(evidence, list) else [],
        "status": conn.status,
        "created_at": conn.created_at.isoformat() if conn.created_at else None,
        "updated_at": conn.updated_at.isoformat() if conn.updated_at else None,
    }


def entry_to_dict(entry: LogbookEntry, *, full: bool = True) -> Dict[str, Any]:
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
        data["datapoints"] = [datapoint_to_dict(dp) for dp in (entry.datapoints or [])]
        data["mentions"] = [mention_to_dict(m) for m in mentions]
        data["people"] = [person_to_dict(p) for p in sorted(people_by_id.values(), key=lambda x: x.display_name.lower())]
        data["location_mentions"] = [location_mention_to_dict(m) for m in location_mentions]
        data["locations"] = [location_to_dict(l) for l in sorted(locations_by_id.values(), key=lambda x: x.display_name.lower())]
    return data


def empty_entry_shape(entry_date: str) -> Dict[str, Any]:
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
