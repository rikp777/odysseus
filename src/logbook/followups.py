"""Daily Logbook people follow-up aggregation."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from core.database import LogbookPerson
from src.logbook import repository as logbook_repo
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils


def _today(today: Optional[date] = None) -> date:
    return today or datetime.now().date()


def _contact_methods(person_data: Dict[str, Any]) -> List[Dict[str, str]]:
    snapshot = person_data.get("contact_snapshot")
    if not isinstance(snapshot, dict):
        return []
    methods = []
    for value in (snapshot.get("emails") or [])[:2]:
        text = str(value or "").strip()
        if text:
            methods.append({"type": "email", "value": text})
    for value in (snapshot.get("phones") or [])[:2]:
        text = str(value or "").strip()
        if text:
            methods.append({"type": "phone", "value": text})
    return methods[:3]


def _action_label(action: str) -> str:
    labels = {
        "check_in": "Check in",
        "meetup": "Plan meetup",
        "message": "Send message",
        "reach_out": "Reach out",
    }
    return labels.get(action or "", "Reach out")


def _connection_counts(connections: List[Any], person_id: str) -> Dict[str, int]:
    counts = {"accepted": 0, "suggested": 0}
    for conn in connections or []:
        if conn.status == "hidden":
            continue
        if conn.person_a_id != person_id and conn.person_b_id != person_id:
            continue
        if conn.status == "accepted":
            counts["accepted"] += 1
        else:
            counts["suggested"] += 1
    return counts


def _status_from_suppression(suppression: Optional[Dict[str, Any]]) -> str:
    if not suppression:
        return "active"
    if suppression.get("type") == "snoozed":
        return "snoozed"
    if suppression.get("type") == "dismissed":
        return "dismissed"
    return "active"


def _followup_item(
    person: LogbookPerson,
    person_data: Dict[str, Any],
    stats: Dict[str, Any],
    connections: List[Any],
) -> Optional[Dict[str, Any]]:
    suggestion = logbook_utils.reconnect_suggestion(person_data, stats, ignore_suppression=True)
    if not suggestion:
        return None
    suppression = logbook_utils.followup_suppression(person_data, stats)
    connection_counts = _connection_counts(connections, person.id)
    return {
        "id": person.id,
        "status": _status_from_suppression(suppression),
        "person": person_data,
        "display_name": person.display_name,
        "relationship_label": getattr(person, "relationship_label", None),
        "last_mentioned": suggestion.get("last_mentioned"),
        "days_since_mentioned": suggestion.get("days_since_mentioned"),
        "level": suggestion.get("level"),
        "suggested_action": suggestion.get("suggested_action"),
        "action_label": _action_label(str(suggestion.get("suggested_action") or "")),
        "message": suggestion.get("message"),
        "reason": suggestion.get("basis"),
        "contact_methods": _contact_methods(person_data),
        "accepted_connections": connection_counts["accepted"],
        "suggested_connections": connection_counts["suggested"],
        "suppression": suppression,
    }


def build_followup_payload(
    db,
    owner: str,
    *,
    include_suppressed: bool = False,
    limit: int = 20,
) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 20), 100))
    people = logbook_repo.person_query(db, owner).all()
    stats = logbook_repo.person_stats(db, owner)
    grouped_connections = logbook_repo.connections_for_people(
        db,
        owner,
        [person.id for person in people],
        include_hidden=True,
        limit_per_person=100,
    )
    items = []
    for person in people:
        data = logbook_utils.with_stats(logbook_serializers.person_to_dict(person), stats.get(person.id, {}))
        item = _followup_item(person, data, stats.get(person.id, {}), grouped_connections.get(person.id, []))
        if not item:
            continue
        if item["status"] != "active" and not include_suppressed:
            continue
        items.append(item)

    status_order = {"active": 0, "snoozed": 1, "dismissed": 2}
    level_order = {"overdue": 0, "due": 1, "soft": 2}
    items.sort(key=lambda item: (
        status_order.get(item.get("status"), 9),
        level_order.get(item.get("level"), 9),
        -(item.get("days_since_mentioned") or 0),
        str(item.get("display_name") or "").lower(),
    ))
    counts = {"active": 0, "snoozed": 0, "dismissed": 0}
    for item in items:
        status = item.get("status")
        if status in counts:
            counts[status] += 1
    return {"items": items[:limit], "counts": counts, "include_suppressed": include_suppressed}


def update_followup_state(
    db,
    owner: str,
    person_id: str,
    *,
    action: str,
    days: Optional[int] = None,
    until: Optional[str] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    person = logbook_repo.load_person_or_404(db, owner, person_id)
    action = str(action or "").strip().lower()
    current = _today(today)
    if action == "snooze":
        if until:
            snoozed_until = logbook_utils.validate_date(until)
        else:
            span = max(1, min(int(days or 14), 365))
            snoozed_until = (current + timedelta(days=span)).isoformat()
        person.followup_snoozed_until = snoozed_until
        person.followup_dismissed_at = None
    elif action == "dismiss":
        person.followup_snoozed_until = None
        person.followup_dismissed_at = current.isoformat()
    elif action == "restore":
        person.followup_snoozed_until = None
        person.followup_dismissed_at = None
    else:
        raise HTTPException(400, "action must be snooze, dismiss, or restore")
    db.flush()
    return {
        "ok": True,
        "action": action,
        "person": logbook_serializers.person_to_dict(person),
    }
