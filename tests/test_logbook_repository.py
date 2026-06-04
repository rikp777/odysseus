from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from core.database import Base, LogbookEntry, LogbookLocation, LogbookLocationMention, LogbookMention
from src.logbook.repository import find_location, get_or_create_location, get_or_create_person, rebuild_entry_links


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
