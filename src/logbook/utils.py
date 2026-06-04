"""Small Daily Logbook parsing, validation, and coercion helpers."""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException


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


def validate_date(value: str) -> str:
    if not value or not DATE_RE.match(value):
        raise HTTPException(400, "Date must use YYYY-MM-DD")
    try:
        datetime.strptime(value, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(400, "Invalid date")
    return value


def normalized_title(value: Optional[str]) -> str:
    title = (value or "").strip()
    return title or "Daily log"


def json_load(value: Optional[str], fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return fallback


def json_dump(value: Any) -> Optional[str]:
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


def aliases(row: Any) -> List[str]:
    raw = json_load(getattr(row, "aliases", None), [])
    if not isinstance(raw, list):
        return []
    return [str(x).strip() for x in raw if str(x).strip()]


def canonical_name(name: str) -> str:
    value = (name or "").strip().strip("@").strip()
    value = value.strip("\"'[]")
    value = unicodedata.normalize("NFKD", value)
    value = "".join(ch for ch in value if not unicodedata.combining(ch))
    value = re.sub(r"[^\w\s-]+", " ", value, flags=re.UNICODE)
    value = re.sub(r"[_\s-]+", " ", value, flags=re.UNICODE)
    return value.strip().lower()


def clean_key(value: str, fallback: str = "datapoint") -> str:
    key = canonical_name(value).replace(" ", "_")
    key = re.sub(r"[^a-z0-9_]+", "", key)
    return key or fallback


def clamp_score(value: Optional[int], *, low: int = 1, high: int = 5) -> Optional[int]:
    if value is None:
        return None
    try:
        n = int(value)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Score must be {low}..{high}")
    if n < low or n > high:
        raise HTTPException(400, f"Score must be {low}..{high}")
    return n


def clamp_confidence(value: Any, default: int = 0) -> int:
    try:
        n = int(value)
    except (TypeError, ValueError):
        n = default
    return max(0, min(100, n))


def parse_mentions(content: str) -> List[Dict[str, Any]]:
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


def parse_locations(content: str) -> List[Dict[str, Any]]:
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


def entry_snippet(content: str, max_len: int = 220) -> str:
    text = re.sub(r"\s+", " ", (content or "").strip())
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def pair_ids(person_a_id: str, person_b_id: str) -> Optional[tuple]:
    if not person_a_id or not person_b_id or person_a_id == person_b_id:
        return None
    return tuple(sorted([person_a_id, person_b_id]))


def add_evidence(existing: List[Dict[str, Any]], entry: Any, snippet: str, source: str = "logbook") -> List[Dict[str, Any]]:
    evidence = [e for e in existing if isinstance(e, dict)]
    if not any(e.get("entry_id") == entry.id and e.get("source", "logbook") == source for e in evidence):
        evidence.append({
            "entry_id": entry.id,
            "entry_date": entry.entry_date,
            "snippet": snippet,
            "source": source,
        })
    return evidence[-8:]


def extract_json_object(text: str) -> Dict[str, Any]:
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


def _days_since_entry_date(value: Any) -> Optional[int]:
    if not value:
        return None
    try:
        seen = datetime.strptime(str(value), "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None
    return max(0, (datetime.now().date() - seen).days)


def _has_linked_contact(data: Dict[str, Any]) -> bool:
    if data.get("contact_uid"):
        return True
    snapshot = data.get("contact_snapshot")
    if not isinstance(snapshot, dict):
        return False
    return bool(snapshot.get("emails") or snapshot.get("phones"))


def reconnect_suggestion(data: Dict[str, Any], stats: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    last_mentioned = stats.get("last_mentioned") or data.get("last_mentioned")
    days = _days_since_entry_date(last_mentioned)
    if days is None or days < 21:
        return None

    name = str(data.get("display_name") or data.get("name") or "this person").strip() or "this person"
    relationship = str(data.get("relationship_label") or data.get("relationship") or "").lower()
    context = " ".join([
        relationship,
        str(data.get("llm_context") or data.get("context") or ""),
        str(data.get("notes") or ""),
    ]).lower()
    has_contact = _has_linked_contact(data)

    action = "reach_out"
    action_text = f"reach out to {name}"
    if any(word in context for word in ("work", "colleague", "client", "boss", "coworker", "project")):
        action = "check_in"
        action_text = f"check in with {name}"
    elif days >= 45 and any(word in context for word in ("friend", "family", "partner", "social", "training", "coach", "team")):
        action = "meetup"
        action_text = f"plan a meetup with {name}"
    elif has_contact:
        action = "message"
        action_text = f"send a message to {name}"

    level = "soft"
    if days >= 90:
        level = "overdue"
    elif days >= 45:
        level = "due"

    return {
        "message": f"You last wrote about {name} {days} days ago. Maybe {action_text}.",
        "suggested_action": action,
        "days_since_mentioned": days,
        "last_mentioned": last_mentioned,
        "level": level,
        "basis": f"Last logbook mention was {last_mentioned}.",
    }


def with_stats(data: Dict[str, Any], stats: Dict[str, Any]) -> Dict[str, Any]:
    days = _days_since_entry_date(stats.get("last_mentioned"))
    data.update({
        "mention_count": int(stats.get("mention_count") or 0),
        "last_mentioned": stats.get("last_mentioned"),
        "days_since_mentioned": days,
    })
    if "relationship_label" in data or "contact_uid" in data or "contact_snapshot" in data:
        data["reconnect_suggestion"] = reconnect_suggestion(data, stats)
    return data
