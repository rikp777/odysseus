"""Daily Logbook AI assist helpers."""

from __future__ import annotations

import itertools
import json
import uuid
from typing import Any, Dict, List

from fastapi import HTTPException
from fastapi.responses import JSONResponse

from core.database import LogbookEntry, LogbookPerson, LogbookPersonConnection
from src.logbook.repository import find_person
from src.logbook.schemas import AI_MODES, ALLOWED_CONNECTION_TYPES, LogbookAIAssist
from src.logbook.utils import (
    add_evidence,
    canonical_name,
    clamp_confidence,
    entry_snippet,
    extract_json_object,
    json_load,
    pair_ids,
    parse_data_links,
    parse_location_links,
    parse_locations,
    parse_mentions,
    parse_person_links,
    validate_date,
)


def deterministic_ai_suggestions(content: str) -> Dict[str, Any]:
    people = []
    seen = set()
    for link in parse_person_links(content or ""):
        canonical = link["target_name"]
        if canonical in seen:
            continue
        seen.add(canonical)
        people.append({
            "display_name": link["target_display_name"] or link["name"],
            "surface_text": link["surface_text"],
            "confidence": 98,
            "reason": "Person link",
        })
    for mention in parse_mentions(content or ""):
        canonical = canonical_name(mention["name"])
        if canonical in seen:
            continue
        seen.add(canonical)
        people.append({
            "display_name": mention["name"],
            "surface_text": mention["surface_text"],
            "confidence": 95,
            "reason": "Explicit @mention",
        })
    datapoints = []
    seen_data = set()
    for link in parse_data_links(content or ""):
        key = canonical_name(link["key"]).replace(" ", "_")
        value = str(link.get("value_text") or "").strip()
        dedupe = (key, value.lower())
        if not key or not value or dedupe in seen_data:
            continue
        seen_data.add(dedupe)
        datapoints.append({
            "key": key,
            "label": link.get("label") or key.replace("_", " ").title(),
            "value_text": value,
            "value_number": None,
            "unit": None,
            "confidence": 95,
            "reason": "Structured data link",
        })
    connections = []
    for a, b in itertools.combinations(people, 2):
        connections.append({
            "person_a": a["display_name"],
            "person_b": b["display_name"],
            "connection_type": "co_mentioned",
            "description": "Mentioned together in this entry",
            "confidence": 65,
            "evidence": entry_snippet(content),
        })
    locations = []
    seen_locations = set()
    for link in parse_location_links(content or ""):
        canonical = link["target_name"]
        if canonical in seen_locations:
            continue
        seen_locations.add(canonical)
        locations.append({
            "display_name": link["target_display_name"] or link["name"],
            "surface_text": link["surface_text"],
            "confidence": 98,
            "reason": "Location link",
        })
    for mention in parse_locations(content or ""):
        canonical = canonical_name(mention["name"])
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
        "datapoint_suggestions": datapoints,
        "location_suggestions": locations,
        "connection_suggestions": connections,
    }


def normalize_ai_payload(mode: str, raw: Dict[str, Any], content: str) -> Dict[str, Any]:
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
    deterministic = deterministic_ai_suggestions(content)
    seen_people = {canonical_name(p.get("display_name", "")) for p in out["people_suggestions"] if isinstance(p, dict)}
    for person in deterministic["people_suggestions"]:
        if canonical_name(person["display_name"]) not in seen_people:
            out["people_suggestions"].append(person)
    seen_locations = {canonical_name(l.get("display_name", "")) for l in out["location_suggestions"] if isinstance(l, dict)}
    for location in deterministic["location_suggestions"]:
        if canonical_name(location["display_name"]) not in seen_locations:
            out["location_suggestions"].append(location)
    seen_data = {
        (canonical_name(d.get("key", "")).replace(" ", "_"), str(d.get("value_text") or "").strip().lower())
        for d in out["datapoint_suggestions"] if isinstance(d, dict)
    }
    for datapoint in deterministic["datapoint_suggestions"]:
        key = canonical_name(datapoint.get("key", "")).replace(" ", "_")
        value = str(datapoint.get("value_text") or "").strip().lower()
        if (key, value) not in seen_data:
            out["datapoint_suggestions"].append(datapoint)
    if not out["connection_suggestions"]:
        out["connection_suggestions"] = deterministic["connection_suggestions"]
    return out


def ai_system_prompt(mode: str, locale: str) -> str:
    return (
        "You help with dyslexia-friendly daily journaling. Preserve the user's meaning, tone, and voice. "
        "Use simple wording, short paragraphs, and bullets when helpful. Do not mention dyslexia unless the user does. "
        "Never shame the user. For clean_spelling, change as little as possible. "
        "For structure_day, turn messy notes into a readable daily log without inventing facts. "
        "For ask_questions, ask at most three short questions that can be answered in a few words. "
        "For reflect, give a gentle reflection, not therapy or medical advice. "
        "For people, locations, and connections, use only evidence from the supplied logbook text. "
        "When mode is structure_day or extract_all, return preview_content that preserves the user's text but marks "
        "confident person mentions as Markdown links like [Jeanine](person:jeanine_peeters). "
        "Mark confident locations as Markdown links like [Panningen](place:panningen). "
        "Mark food or other trackable daily data as data links like [eiwitrijk ontbijt](data:food). "
        "Use lower_snake_case slugs. Do not link uncertain names or vague places. "
        "Locations are places such as home, gym, office, city, route, venue, or clinic. "
        "Connections are possible suggestions, not facts, unless the user accepts them. "
        f"Locale: {locale}. Mode: {mode}. "
        "Return strict JSON only with keys: ok, mode, preview_content, summary, questions, mood_suggestion, "
        "datapoint_suggestions, people_suggestions, location_suggestions, connection_suggestions, reflection. "
        "connection_suggestions items must include person_a, person_b, connection_type, description, confidence, evidence."
    )


def ai_status(owner: str) -> Dict[str, Any]:
    try:
        from src.endpoint_resolver import resolve_endpoint
    except Exception:
        return {
            "ok": True,
            "available": False,
            "reason": "AI helpers are unavailable",
        }

    url, model, _headers = resolve_endpoint("utility", owner=owner)
    source = "utility/default"
    if not url or not model:
        url, model, _headers = resolve_endpoint("default", owner=owner)
    available = bool(url and model)
    return {
        "ok": True,
        "available": available,
        "source": source if available else None,
        "model": model if available else None,
        "reason": None if available else "No utility or default LLM provider/model is configured",
    }


async def run_ai_assist(owner: str, payload: LogbookAIAssist) -> JSONResponse | Dict[str, Any]:
    mode = (payload.mode or "").strip()
    if mode not in AI_MODES:
        raise HTTPException(400, "Unknown AI assist mode")
    entry_date = validate_date(payload.entry_date)
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

    messages = [
        {"role": "system", "content": ai_system_prompt(mode, locale)},
        {
            "role": "user",
            "content": json.dumps({
                "entry_date": entry_date,
                "mode": mode,
                "content": payload.content or "",
                "current_entry": payload.current_entry or {},
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
    return normalize_ai_payload(mode, extract_json_object(cleaned), payload.content or "")


def store_ai_connection_suggestions(
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
        confidence = clamp_confidence(suggestion.get("confidence"))
        if confidence < 50:
            continue
        person_a = find_person(db, owner, str(suggestion.get("person_a") or ""), people)
        person_b = find_person(db, owner, str(suggestion.get("person_b") or ""), people)
        if not person_a or not person_b:
            continue
        pair = pair_ids(person_a.id, person_b.id)
        if not pair:
            continue
        a_id, b_id = pair
        connection_type = str(suggestion.get("connection_type") or "unknown").strip().lower()
        if connection_type not in ALLOWED_CONNECTION_TYPES:
            connection_type = "unknown"
        evidence_text = entry_snippet(str(suggestion.get("evidence") or suggestion.get("description") or entry.content or ""))
        conn = db.query(LogbookPersonConnection).filter(
            LogbookPersonConnection.owner == owner,
            LogbookPersonConnection.person_a_id == a_id,
            LogbookPersonConnection.person_b_id == b_id,
            LogbookPersonConnection.connection_type == connection_type,
        ).first()
        if not conn:
            conn = LogbookPersonConnection(
                id=str(uuid.uuid4()),
                owner=owner,
                person_a_id=a_id,
                person_b_id=b_id,
                connection_type=connection_type,
                description=str(suggestion.get("description") or "").strip() or None,
                strength=1 if confidence < 75 else 2,
                confidence=confidence,
                evidence_json="[]",
                status="suggested",
            )
            db.add(conn)
        elif conn.status == "accepted" and confidence <= (conn.confidence or 0):
            evidence = add_evidence(json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
            conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
            created_or_updated.append(conn)
            continue
        elif conn.status == "hidden":
            evidence = add_evidence(json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
            conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
            created_or_updated.append(conn)
            continue
        conn.description = str(suggestion.get("description") or conn.description or "").strip() or None
        conn.confidence = max(conn.confidence or 0, confidence)
        conn.strength = max(conn.strength or 1, 1 if confidence < 75 else 2)
        evidence = add_evidence(json_load(conn.evidence_json, []), entry, evidence_text, source="ai")
        conn.evidence_json = json.dumps(evidence, ensure_ascii=False)
        created_or_updated.append(conn)
    return created_or_updated
