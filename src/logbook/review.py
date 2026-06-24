"""Read-only Daily Logbook review aggregation."""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

from core.database import LogbookEntry
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils


def _parse_date(value: Optional[str], fallback: date) -> date:
    if not value:
        return fallback
    validated = logbook_utils.validate_date(value)
    return datetime.strptime(validated, "%Y-%m-%d").date()


def review_range(
    *,
    period: str = "week",
    anchor: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    today: Optional[date] = None,
) -> Tuple[str, str, str]:
    current = _parse_date(anchor, today or datetime.now().date())
    kind = (period or "week").strip().lower()
    if kind not in {"week", "month"}:
        kind = "week"

    if start or end:
        start_date = _parse_date(start, current)
        end_date = _parse_date(end, start_date)
        if end_date < start_date:
            start_date, end_date = end_date, start_date
        return start_date.isoformat(), end_date.isoformat(), "custom"

    if kind == "month":
        start_date = current.replace(day=1)
        next_month = (start_date.replace(day=28) + timedelta(days=4)).replace(day=1)
        end_date = next_month - timedelta(days=1)
        return start_date.isoformat(), end_date.isoformat(), "month"

    start_date = current - timedelta(days=current.weekday())
    end_date = start_date + timedelta(days=6)
    return start_date.isoformat(), end_date.isoformat(), "week"


def _entry_snippet(entry: LogbookEntry, limit: int = 180) -> str:
    return logbook_utils.entry_snippet(entry.summary or entry.content or "", limit)


def _entry_people(entry: LogbookEntry) -> List[str]:
    people = {}
    for mention in entry.mentions or []:
        if mention.person:
            people[mention.person.id] = mention.person.display_name
    return sorted(people.values(), key=str.lower)


def _entry_places(entry: LogbookEntry) -> List[str]:
    places = {}
    for mention in entry.location_mentions or []:
        if mention.location:
            places[mention.location.id] = mention.location.display_name
    return sorted(places.values(), key=str.lower)


def _score_summary(entries: Iterable[LogbookEntry], field: str) -> Dict[str, Any]:
    values = [getattr(entry, field, None) for entry in entries]
    numeric = [int(value) for value in values if value is not None]
    if not numeric:
        return {"count": 0, "average": None, "min": None, "max": None}
    return {
        "count": len(numeric),
        "average": round(sum(numeric) / len(numeric), 1),
        "min": min(numeric),
        "max": max(numeric),
    }


def _format_number(value: Any) -> str:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return str(value or "")
    if num.is_integer():
        return str(int(num))
    return f"{num:.1f}".rstrip("0").rstrip(".")


def _score_evidence(
    entries: List[LogbookEntry],
    field: str,
    label: str,
    predicate,
    *,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    rows = []
    for entry in sorted(entries, key=lambda item: item.entry_date, reverse=True):
        value = getattr(entry, field, None)
        if value is None:
            continue
        numeric = int(value)
        if not predicate(numeric):
            continue
        rows.append({
            "date": entry.entry_date,
            "label": label,
            "value": numeric,
            "unit": "/5",
            "snippet": _entry_snippet(entry, 110),
        })
    return rows[:limit]


def _entity_evidence(
    entries: List[LogbookEntry],
    entity_id: str,
    label: str,
    attr: str,
    id_attr: str,
    *,
    limit: int = 3,
) -> List[Dict[str, Any]]:
    rows = []
    for entry in sorted(entries, key=lambda item: item.entry_date, reverse=True):
        mentions = getattr(entry, attr, None) or []
        if not any(getattr(mention, id_attr, None) == entity_id for mention in mentions):
            continue
        rows.append({
            "date": entry.entry_date,
            "label": label,
            "snippet": _entry_snippet(entry, 110),
        })
    return rows[:limit]


def _datapoint_review(entries: List[LogbookEntry], *, limit: int = 12) -> List[Dict[str, Any]]:
    grouped: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        for dp in entry.datapoints or []:
            key = logbook_utils.clean_key(dp.key or dp.label)
            item = grouped.setdefault(key, {
                "key": key,
                "label": dp.label or key.replace("_", " ").title(),
                "unit": dp.unit,
                "count": 0,
                "numeric_count": 0,
                "average": None,
                "latest_date": None,
                "latest_value": None,
                "series": [],
                "_total": 0.0,
            })
            if dp.label and not item.get("label"):
                item["label"] = dp.label
            if dp.unit and not item.get("unit"):
                item["unit"] = dp.unit
            item["count"] += 1
            value = dp.value_number if dp.value_number is not None else dp.value_text
            item["latest_date"] = entry.entry_date
            item["latest_value"] = value
            point = {"date": entry.entry_date, "value_text": dp.value_text, "value_number": dp.value_number, "unit": dp.unit}
            item["series"].append(point)
            if dp.value_number is not None:
                item["numeric_count"] += 1
                item["_total"] += float(dp.value_number)
                item["average"] = round(item["_total"] / item["numeric_count"], 2)

    out = []
    for item in grouped.values():
        item.pop("_total", None)
        item["series"] = item["series"][-14:]
        out.append(item)
    out.sort(key=lambda item: (-item["count"], str(item.get("latest_date") or ""), item["label"].lower()))
    return out[:limit]


def _top_people(entries: List[LogbookEntry], *, limit: int = 8) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        seen = set()
        for mention in entry.mentions or []:
            person = mention.person
            if not person or person.id in seen:
                continue
            seen.add(person.id)
            data = rows.setdefault(person.id, {
                "id": person.id,
                "display_name": person.display_name,
                "relationship_label": getattr(person, "relationship_label", None),
                "count": 0,
                "last_mentioned": None,
            })
            data["count"] += 1
            data["last_mentioned"] = max(data["last_mentioned"] or "", entry.entry_date)
    out = list(rows.values())
    out.sort(key=lambda item: (-item["count"], str(item.get("last_mentioned") or ""), item["display_name"].lower()))
    return out[:limit]


def _top_places(entries: List[LogbookEntry], *, limit: int = 8) -> List[Dict[str, Any]]:
    rows: Dict[str, Dict[str, Any]] = {}
    for entry in entries:
        seen = set()
        for mention in entry.location_mentions or []:
            location = mention.location
            if not location or location.id in seen:
                continue
            seen.add(location.id)
            data = rows.setdefault(location.id, {
                "id": location.id,
                "display_name": location.display_name,
                "location_type": getattr(location, "location_type", None),
                "count": 0,
                "last_mentioned": None,
            })
            data["count"] += 1
            data["last_mentioned"] = max(data["last_mentioned"] or "", entry.entry_date)
    out = list(rows.values())
    out.sort(key=lambda item: (-item["count"], str(item.get("last_mentioned") or ""), item["display_name"].lower()))
    return out[:limit]


def _reconnect_candidates(db, owner: str, *, limit: int = 6) -> List[Dict[str, Any]]:
    stats = logbook_repo.person_stats(db, owner)
    people = logbook_repo.person_query(db, owner).all()
    candidates = []
    for person in people:
        data = logbook_utils.with_stats(logbook_serializers.person_to_dict(person), stats.get(person.id, {}))
        suggestion = data.get("reconnect_suggestion")
        if not suggestion:
            continue
        candidates.append({
            "id": person.id,
            "display_name": person.display_name,
            "relationship_label": getattr(person, "relationship_label", None),
            "last_mentioned": data.get("last_mentioned"),
            "days_since_mentioned": data.get("days_since_mentioned"),
            "suggested_action": suggestion.get("suggested_action"),
            "message": suggestion.get("message"),
            "level": suggestion.get("level"),
        })
    candidates.sort(key=lambda item: (-(item.get("days_since_mentioned") or 0), item["display_name"].lower()))
    return candidates[:limit]


def _highlights(entries: List[LogbookEntry], *, limit: int = 8) -> List[Dict[str, Any]]:
    rows = []
    for entry in sorted(entries, key=lambda item: item.entry_date, reverse=True):
        snippet = _entry_snippet(entry)
        if not snippet:
            continue
        rows.append({
            "id": entry.id,
            "date": entry.entry_date,
            "title": entry.title or "Daily log",
            "snippet": snippet,
            "mood_label": entry.mood_label,
            "people": _entry_people(entry),
            "places": _entry_places(entry),
        })
    return rows[:limit]


def _is_sleep_datapoint(item: Dict[str, Any]) -> bool:
    key = str(item.get("key") or "").lower()
    label = str(item.get("label") or "").lower()
    return "sleep" in key or "sleep" in label


def _datapoint_evidence(item: Dict[str, Any], predicate, *, limit: int = 3) -> List[Dict[str, Any]]:
    rows = []
    for point in reversed(item.get("series") or []):
        value = point.get("value_number")
        if value is None or not predicate(float(value)):
            continue
        rows.append({
            "date": point.get("date"),
            "label": item.get("label") or item.get("key") or "Data",
            "value": _format_number(value),
            "unit": point.get("unit") or item.get("unit"),
        })
    return rows[:limit]


def _insight(
    insight_id: str,
    kind: str,
    level: str,
    title: str,
    detail: str,
    evidence: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "id": insight_id,
        "kind": kind,
        "level": level,
        "title": title,
        "detail": detail,
        "evidence": evidence or [],
    }


def _review_insights(
    entries: List[LogbookEntry],
    scores: Dict[str, Dict[str, Any]],
    datapoints: List[Dict[str, Any]],
    top_people: List[Dict[str, Any]],
    top_places: List[Dict[str, Any]],
    reconnect_candidates: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    insights: List[Dict[str, Any]] = []

    energy = scores.get("energy") or {}
    if energy.get("count") and energy.get("average") is not None and float(energy["average"]) <= 2.5:
        insights.append(_insight(
            "low_energy",
            "score",
            "warning",
            "Energy ran low",
            f"Average energy was {_format_number(energy['average'])}/5 across {energy['count']} logged day"
            f"{'' if energy['count'] == 1 else 's'}.",
            _score_evidence(entries, "energy_score", "Energy", lambda value: value <= 2),
        ))

    stress = scores.get("stress") or {}
    if stress.get("count") and stress.get("average") is not None and float(stress["average"]) >= 4:
        insights.append(_insight(
            "high_stress",
            "score",
            "warning",
            "Stress stayed high",
            f"Average stress was {_format_number(stress['average'])}/5 across {stress['count']} logged day"
            f"{'' if stress['count'] == 1 else 's'}.",
            _score_evidence(entries, "stress_score", "Stress", lambda value: value >= 4),
        ))

    mood = scores.get("mood") or {}
    if mood.get("count") and mood.get("min") is not None and int(mood["min"]) <= 2:
        insights.append(_insight(
            "low_mood_day",
            "score",
            "notice",
            "Low mood showed up",
            "At least one logged day had a mood score of 2/5 or lower.",
            _score_evidence(entries, "mood_score", "Mood", lambda value: value <= 2),
        ))

    sleep = next((item for item in datapoints if _is_sleep_datapoint(item) and item.get("average") is not None), None)
    if sleep and float(sleep["average"]) < 6.5:
        label = sleep.get("label") or "Sleep"
        count = int(sleep.get("numeric_count") or sleep.get("count") or 0)
        noun = "entry" if count == 1 else "entries"
        unit = sleep.get("unit") or ""
        unit_text = f" {unit}" if unit else ""
        insights.append(_insight(
            "low_sleep_average",
            "datapoint",
            "notice",
            "Sleep averaged low",
            f"Average {label} was {_format_number(sleep['average'])}{unit_text} across {count} logged {noun}.",
            _datapoint_evidence(sleep, lambda value: value < 6.5),
        ))

    if top_people and int(top_people[0].get("count") or 0) >= 2:
        person = top_people[0]
        name = person.get("display_name") or "Someone"
        count = int(person.get("count") or 0)
        insights.append(_insight(
            f"recurring_person_{person.get('id') or logbook_utils.clean_key(name)}",
            "person",
            "positive",
            f"{name} came up often",
            f"Mentioned on {count} logged day{'' if count == 1 else 's'} in this range.",
            _entity_evidence(entries, person.get("id") or "", name, "mentions", "person_id"),
        ))

    if top_places and int(top_places[0].get("count") or 0) >= 2:
        place = top_places[0]
        name = place.get("display_name") or "A place"
        count = int(place.get("count") or 0)
        insights.append(_insight(
            f"recurring_place_{place.get('id') or logbook_utils.clean_key(name)}",
            "place",
            "positive",
            f"{name} was a recurring place",
            f"Mentioned on {count} logged day{'' if count == 1 else 's'} in this range.",
            _entity_evidence(entries, place.get("id") or "", name, "location_mentions", "location_id"),
        ))

    if reconnect_candidates:
        person = reconnect_candidates[0]
        name = person.get("display_name") or "Someone"
        evidence = []
        if person.get("last_mentioned"):
            evidence.append({
                "date": person.get("last_mentioned"),
                "label": name,
                "value": f"{person.get('days_since_mentioned')} days" if person.get("days_since_mentioned") else "",
            })
        insights.append(_insight(
            f"reconnect_{person.get('id') or logbook_utils.clean_key(name)}",
            "person",
            "notice",
            f"Reconnect with {name}",
            person.get("message") or "This person has not appeared in recent log entries.",
            evidence,
        ))

    return insights[:6]


def build_review_payload(
    db,
    owner: str,
    *,
    period: str = "week",
    anchor: Optional[str] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
) -> Dict[str, Any]:
    start_date, end_date, resolved_period = review_range(period=period, anchor=anchor, start=start, end=end)
    entries = (
        logbook_repo.entry_query(db, owner)
        .filter(LogbookEntry.entry_date >= start_date, LogbookEntry.entry_date <= end_date)
        .order_by(LogbookEntry.entry_date.asc(), LogbookEntry.updated_at.asc())
        .all()
    )
    mood_counts = Counter(entry.mood_label for entry in entries if entry.mood_label)
    entry_dates = {entry.entry_date for entry in entries}
    range_days = (datetime.strptime(end_date, "%Y-%m-%d").date() - datetime.strptime(start_date, "%Y-%m-%d").date()).days + 1
    stats = {
        "entry_count": len(entries),
        "days_with_entries": len(entry_dates),
        "range_days": range_days,
        "people_count": len({mention.person_id for entry in entries for mention in (entry.mentions or [])}),
        "place_count": len({mention.location_id for entry in entries for mention in (entry.location_mentions or [])}),
        "datapoint_count": sum(len(entry.datapoints or []) for entry in entries),
    }
    scores = {
        "mood": _score_summary(entries, "mood_score"),
        "energy": _score_summary(entries, "energy_score"),
        "stress": _score_summary(entries, "stress_score"),
    }
    datapoints = _datapoint_review(entries)
    top_people = _top_people(entries)
    top_places = _top_places(entries)
    reconnect_candidates = _reconnect_candidates(db, owner)
    return {
        "period": resolved_period,
        "range": {"start": start_date, "end": end_date, "days": range_days},
        "stats": stats,
        "moods": [{"label": label, "count": count} for label, count in mood_counts.most_common()],
        "scores": scores,
        "datapoints": datapoints,
        "top_people": top_people,
        "top_places": top_places,
        "reconnect_candidates": reconnect_candidates,
        "insights": _review_insights(entries, scores, datapoints, top_people, top_places, reconnect_candidates),
        "highlights": _highlights(entries),
    }
