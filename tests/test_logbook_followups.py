import json
from datetime import date, datetime

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, LogbookEntry
from src.logbook import followups as logbook_followups
from src.logbook import serializers as logbook_serializers
from src.logbook import utils as logbook_utils
from src.logbook.repository import get_or_create_person, person_stats, rebuild_entry_links


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _entry(db, owner, entry_id, entry_date, content):
    entry = LogbookEntry(
        id=entry_id,
        owner=owner,
        entry_date=entry_date,
        title="Daily log",
        content=content,
    )
    db.add(entry)
    db.flush()
    rebuild_entry_links(db, owner, entry)
    return entry


def test_logbook_followup_payload_and_suppression(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 10)

    monkeypatch.setattr(logbook_utils, "datetime", FixedDatetime)
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        person = get_or_create_person(db, "owner-1", "Old Friend")
        person.relationship_label = "friend"
        person.contact_snapshot_json = json.dumps({
            "emails": ["old@example.test"],
            "phones": ["+311234"],
        })
        get_or_create_person(db, "other-owner", "Other Friend")
        _entry(db, "owner-1", "entry-1", "2026-04-01", "Dinner with [Old Friend](person:old_friend).")
        _entry(db, "other-owner", "entry-2", "2026-04-01", "Other saw [Other Friend](person:other_friend).")
        db.commit()

        payload = logbook_followups.build_followup_payload(db, "owner-1")
        assert payload["counts"] == {"active": 1, "snoozed": 0, "dismissed": 0}
        item = payload["items"][0]
        assert item["display_name"] == "Old Friend"
        assert item["status"] == "active"
        assert item["action_label"] == "Plan meetup"
        assert item["contact_methods"][0] == {"type": "email", "value": "old@example.test"}
        assert item["last_mentioned"] == "2026-04-01"

        logbook_followups.update_followup_state(
            db,
            "owner-1",
            person.id,
            action="snooze",
            days=14,
            today=date(2026, 6, 10),
        )
        db.commit()
        assert logbook_followups.build_followup_payload(db, "owner-1")["items"] == []
        snoozed = logbook_followups.build_followup_payload(db, "owner-1", include_suppressed=True)["items"][0]
        assert snoozed["status"] == "snoozed"
        assert snoozed["suppression"] == {"type": "snoozed", "until": "2026-06-24"}

        data = logbook_utils.with_stats(
            logbook_serializers.person_to_dict(person),
            person_stats(db, "owner-1")[person.id],
        )
        assert data["reconnect_suggestion"] is None
        assert data["followup_suppression"]["type"] == "snoozed"

        logbook_followups.update_followup_state(db, "owner-1", person.id, action="restore")
        logbook_followups.update_followup_state(
            db,
            "owner-1",
            person.id,
            action="dismiss",
            today=date(2026, 6, 10),
        )
        db.commit()
        dismissed = logbook_followups.build_followup_payload(db, "owner-1", include_suppressed=True)["items"][0]
        assert dismissed["status"] == "dismissed"
        assert dismissed["suppression"] == {"type": "dismissed", "at": "2026-06-10"}
    finally:
        db.close()
