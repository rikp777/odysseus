from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, LogbookDataPoint, LogbookEntry
import src.logbook_context as logbook_context
from src.logbook.repository import get_or_create_location, get_or_create_person, rebuild_entry_links


def _session_factory(monkeypatch):
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    monkeypatch.setattr(logbook_context, "SessionLocal", SessionLocal)
    return SessionLocal


def test_list_range_uses_shared_logbook_lookup_helpers(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)
    owner = "owner-1"
    db = SessionLocal()
    try:
        get_or_create_person(db, owner, "Nora", aliases_=["N\u00f3ra"])
        get_or_create_location(db, owner, "Gym")
        entry = LogbookEntry(
            id="entry-1",
            owner=owner,
            entry_date="2026-06-04",
            title="Training day",
            content="Coffee with [Nora](person:nora) at [Gym](place:gym).",
        )
        db.add(entry)
        db.flush()
        rebuild_entry_links(db, owner, entry)
        db.add(LogbookDataPoint(
            id="dp-1",
            entry_id=entry.id,
            key="sleep_quality",
            label="Sleep Quality",
            value_text="good",
            sort_order=0,
        ))
        db.commit()
    finally:
        db.close()

    result = logbook_context.list_range(
        owner,
        person="N\u00f3ra",
        place="Gym",
        datapoint_key="Sleep Quality",
        limit=5,
    )

    assert result["ok"] is True
    assert [entry["date"] for entry in result["entries"]] == ["2026-06-04"]
    assert result["entries"][0]["people"] == ["Nora"]
    assert result["entries"][0]["places"] == ["Gym"]
    assert result["entries"][0]["datapoints"][0]["key"] == "sleep_quality"


def test_run_tool_review_returns_ok(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)

    result = logbook_context.run_tool("owner-1", {"action": "review", "period": "week"})
    assert result["ok"] is True
    assert "Review" in result["output"]


def test_run_tool_followups_returns_ok(monkeypatch):
    SessionLocal = _session_factory(monkeypatch)

    result = logbook_context.run_tool("owner-1", {"action": "followups"})
    assert result["ok"] is True
    assert "Follow-ups" in result["output"]
