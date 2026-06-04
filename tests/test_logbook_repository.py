from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import (
    Base,
    LogbookDataPoint,
    LogbookEntry,
    LogbookEntryRevision,
    LogbookLocation,
    LogbookLocationMention,
    LogbookMention,
)
from src.logbook.repository import (
    create_entry_revision,
    entry_will_change,
    find_location,
    get_or_create_location,
    get_or_create_person,
    rebuild_entry_links,
    replace_datapoints,
    restore_entry_revision,
)
from src.logbook.schemas import LogbookDataPointIn, LogbookEntryUpdate


def test_rebuild_entry_links_only_uses_explicit_logbook_links():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    get_or_create_person(db, owner, "Jan")
    get_or_create_location(db, owner, "Gym")
    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Daily log",
        content="Talked with [Jan](person:jan) at [Gym](place:gym).",
    )
    db.add(entry)
    db.flush()

    rebuild_entry_links(db, owner, entry)
    db.flush()
    assert db.query(LogbookMention).count() == 1
    assert db.query(LogbookLocationMention).count() == 1

    entry.content = "Talked with Jan at Gym."
    rebuild_entry_links(db, owner, entry)
    db.flush()

    assert db.query(LogbookMention).count() == 0
    assert db.query(LogbookLocationMention).count() == 0


def test_hidden_location_is_not_linked_or_duplicated():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    hidden = get_or_create_location(db, owner, "Gym")
    hidden.hidden = True
    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Daily log",
        content="Trained at [Gym](place:gym) and later #Gym.",
    )
    db.add(entry)
    db.flush()

    assert find_location(db, owner, "Gym") is None
    assert find_location(db, owner, "Gym", include_hidden=True).id == hidden.id

    rebuild_entry_links(db, owner, entry)
    db.flush()

    assert db.query(LogbookLocation).count() == 1
    assert db.query(LogbookLocationMention).count() == 0


def test_entry_revision_snapshots_and_restores_entry_fields_and_datapoints():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Training day",
        content="Trained with [Jan](person:jan).",
        mood_label="good",
        mood_score=4,
    )
    db.add(entry)
    db.flush()
    db.add(LogbookDataPoint(
        id="dp-1",
        entry_id=entry.id,
        key="food",
        label="Food",
        value_text="breakfast",
        value_number=None,
        unit=None,
        sort_order=0,
    ))
    db.flush()

    unchanged = LogbookEntryUpdate(
        title="Training day",
        content="Trained with [Jan](person:jan).",
        mood_label="good",
        mood_score=4,
        datapoints=[LogbookDataPointIn(key="food", label="Food", value_text="breakfast", sort_order=0)],
    )
    changed = LogbookEntryUpdate(content="Rest day.")

    assert entry_will_change(entry, unchanged) is False
    assert entry_will_change(entry, changed) is True

    revision = create_entry_revision(db, entry, source="manual_save")
    assert revision is not None
    assert db.query(LogbookEntryRevision).count() == 1

    entry.title = "Changed"
    entry.content = "Rest day."
    entry.mood_label = "flat"
    entry.mood_score = 2
    replace_datapoints(db, entry, [LogbookDataPointIn(key="sleep", label="Sleep", value_text="7h")])
    db.flush()

    restore_entry_revision(db, owner, entry, revision)
    db.flush()

    assert entry.title == "Training day"
    assert entry.content == "Trained with [Jan](person:jan)."
    assert entry.mood_label == "good"
    assert entry.mood_score == 4
    restored_points = db.query(LogbookDataPoint).filter(LogbookDataPoint.entry_id == entry.id).all()
    assert [(dp.key, dp.label, dp.value_text) for dp in restored_points] == [("food", "Food", "breakfast")]
    assert db.query(LogbookMention).count() == 1
