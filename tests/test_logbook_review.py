from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from core.database import Base, LogbookDataPoint, LogbookEntry
from src.logbook.repository import get_or_create_location, get_or_create_person, rebuild_entry_links
from src.logbook.review import build_review_payload


def _session_factory():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    return sessionmaker(bind=engine)


def _entry(db, owner, entry_id, entry_date, content, **fields):
    entry = LogbookEntry(
        id=entry_id,
        owner=owner,
        entry_date=entry_date,
        title=fields.pop("title", "Daily log"),
        content=content,
        **fields,
    )
    db.add(entry)
    db.flush()
    rebuild_entry_links(db, owner, entry)
    return entry


def test_logbook_review_aggregates_owner_scoped_week():
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        get_or_create_person(db, "owner-1", "Nora", aliases_=["Nor"])
        get_or_create_person(db, "owner-1", "Old Friend", aliases_=["Oldie"])
        get_or_create_location(db, "owner-1", "Gym")
        get_or_create_person(db, "other-owner", "Other Person")
        get_or_create_location(db, "other-owner", "Other Place")

        first = _entry(
            db,
            "owner-1",
            "entry-1",
            "2026-06-02",
            "Training with [Nora](person:nora) at [Gym](place:gym).",
            mood_label="good",
            mood_score=4,
            energy_score=5,
            stress_score=2,
        )
        db.add(LogbookDataPoint(
            id="dp-1",
            entry_id=first.id,
            key="sleep",
            label="Sleep",
            value_text="7h",
            value_number=7,
            unit="h",
            sort_order=0,
        ))
        second = _entry(
            db,
            "owner-1",
            "entry-2",
            "2026-06-04",
            "Coffee with [Nor](person:nora).",
            mood_label="tired",
            mood_score=2,
            energy_score=2,
            stress_score=4,
        )
        db.add(LogbookDataPoint(
            id="dp-2",
            entry_id=second.id,
            key="sleep",
            label="Sleep",
            value_text="5h",
            value_number=5,
            unit="h",
            sort_order=0,
        ))
        _entry(
            db,
            "owner-1",
            "entry-old",
            "2026-03-01",
            "Dinner with [Old Friend](person:old_friend).",
        )
        _entry(
            db,
            "other-owner",
            "entry-other",
            "2026-06-04",
            "Other user saw [Other Person](person:other_person) at [Other Place](place:other_place).",
            mood_label="other",
        )
        db.commit()

        data = build_review_payload(db, "owner-1", period="week", anchor="2026-06-04")
    finally:
        db.close()

    assert data["range"] == {"start": "2026-06-01", "end": "2026-06-07", "days": 7}
    assert data["stats"]["entry_count"] == 2
    assert data["stats"]["people_count"] == 1
    assert data["stats"]["place_count"] == 1
    assert data["scores"]["energy"]["average"] == 3.5
    assert data["datapoints"][0]["key"] == "sleep"
    assert data["datapoints"][0]["average"] == 6.0
    assert data["top_people"][0]["display_name"] == "Nora"
    assert data["top_people"][0]["count"] == 2
    assert data["top_places"][0]["display_name"] == "Gym"
    assert [item["label"] for item in data["moods"]] == ["good", "tired"]
    assert all("Other" not in item["snippet"] for item in data["highlights"])
    assert data["reconnect_candidates"][0]["display_name"] == "Old Friend"
    insights = {item["id"]: item for item in data["insights"]}
    assert insights["low_sleep_average"]["evidence"][0]["date"] == "2026-06-04"
    assert insights["low_mood_day"]["evidence"][0]["value"] == 2
    assert any(item["title"] == "Nora came up often" for item in data["insights"])
    assert any(item["title"] == "Reconnect with Old Friend" for item in data["insights"])


def test_logbook_review_accepts_custom_range():
    SessionLocal = _session_factory()
    db = SessionLocal()
    try:
        _entry(db, "owner-1", "entry-1", "2026-06-01", "One")
        _entry(db, "owner-1", "entry-2", "2026-06-10", "Two")
        db.commit()

        data = build_review_payload(db, "owner-1", start="2026-06-03", end="2026-06-12")
    finally:
        db.close()

    assert data["period"] == "custom"
    assert data["stats"]["entry_count"] == 1
    assert data["highlights"][0]["date"] == "2026-06-10"
