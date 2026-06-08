import json

import pytest
from fastapi import HTTPException
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
    LogbookPersonConnection,
    LogbookPersonFact,
)
from src.logbook.repository import (
    connections_for_people,
    create_entry_revision,
    entry_will_change,
    find_location,
    find_location_duplicate,
    get_or_create_location,
    get_or_create_person,
    link_person_suggestion,
    location_mention_count,
    merge_person_facts,
    person_facts,
    person_facts_for_people,
    rebuild_entry_links,
    replace_datapoints,
    restore_entry_revision,
    update_manual_connection,
    upsert_manual_connection,
    upsert_person_fact,
)
from src.logbook.schemas import LogbookDataPointIn, LogbookEntryUpdate
from src.logbook.ai import store_ai_person_suggestion_details
from src.logbook.serializers import connection_summary_to_dict


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


def test_location_duplicate_check_includes_aliases_and_hidden_places():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    gym = get_or_create_location(db, owner, "Gym", aliases_=["Training Place"])
    hidden = get_or_create_location(db, owner, "Old Office", aliases_=["Archive"])
    hidden.hidden = True
    office = get_or_create_location(db, owner, "Office")
    db.flush()

    assert find_location_duplicate(db, owner, ["Training Place"]).id == gym.id
    assert find_location_duplicate(db, owner, ["Archive"]).id == hidden.id
    assert find_location_duplicate(db, owner, ["Office"], exclude_id=office.id) is None
    assert find_location_duplicate(db, owner, ["Gym"], exclude_id=office.id).id == gym.id


def test_location_mention_count_tracks_unlink_and_unused_places_can_delete():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    gym = get_or_create_location(db, owner, "Gym")
    unused = get_or_create_location(db, owner, "Old Cafe")
    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Daily log",
        content="Trained at [Gym](place:gym).",
    )
    db.add(entry)
    db.flush()

    rebuild_entry_links(db, owner, entry)
    db.flush()
    assert location_mention_count(db, gym.id) == 1
    assert location_mention_count(db, unused.id) == 0

    db.delete(unused)
    db.flush()
    assert db.query(LogbookLocation).filter(LogbookLocation.id == unused.id).first() is None

    entry.content = "Trained at Gym."
    rebuild_entry_links(db, owner, entry)
    db.flush()
    assert location_mention_count(db, gym.id) == 0


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


def test_connections_for_people_returns_visible_person_summaries():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    jan = get_or_create_person(db, owner, "Jan")
    noor = get_or_create_person(db, owner, "Noor")
    mila = get_or_create_person(db, owner, "Mila")
    db.flush()
    db.add(LogbookPersonConnection(
        id="conn-1",
        owner=owner,
        person_a_id=jan.id,
        person_b_id=noor.id,
        connection_type="friend",
        description="Often mentioned together.",
        strength=3,
        confidence=82,
        evidence_json=json.dumps([{"entry_date": "2026-06-05", "snippet": "Coffee after training."}]),
        status="accepted",
    ))
    db.add(LogbookPersonConnection(
        id="conn-hidden",
        owner=owner,
        person_a_id=jan.id,
        person_b_id=mila.id,
        connection_type="work",
        description="Hidden suggestion.",
        strength=1,
        confidence=60,
        evidence_json="[]",
        status="hidden",
    ))
    db.flush()

    grouped = connections_for_people(db, owner, [jan.id, noor.id, mila.id])

    assert [conn.id for conn in grouped[jan.id]] == ["conn-1"]
    assert [conn.id for conn in grouped[noor.id]] == ["conn-1"]
    assert grouped[mila.id] == []
    summary = connection_summary_to_dict(grouped[jan.id][0], jan.id)
    assert summary["other_person"]["display_name"] == "Noor"
    assert summary["connection_type"] == "friend"
    assert summary["status"] == "accepted"
    assert summary["evidence_count"] == 1
    assert summary["latest_evidence"]["entry_date"] == "2026-06-05"
    assert connection_summary_to_dict(grouped[jan.id][0], "missing-person") is None


def test_manual_connection_upsert_and_update_are_duplicate_safe():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    jan = get_or_create_person(db, owner, "Jan")
    noor = get_or_create_person(db, owner, "Noor")
    db.flush()

    conn, duplicate = upsert_manual_connection(
        db,
        owner,
        person_a_id=noor.id,
        person_b_id=jan.id,
        connection_type="Friend",
        description="Training friends.",
        strength=4,
        confidence=90,
        status="accepted",
    )
    db.flush()

    assert duplicate is False
    assert (conn.person_a_id, conn.person_b_id) == tuple(sorted([jan.id, noor.id]))
    assert conn.connection_type == "friend"
    assert conn.description == "Training friends."
    assert conn.strength == 4
    assert conn.confidence == 90
    assert conn.status == "accepted"

    same, duplicate = upsert_manual_connection(
        db,
        owner,
        person_a_id=jan.id,
        person_b_id=noor.id,
        connection_type="friend",
        description="Updated note.",
        strength=2,
        confidence=70,
        status="suggested",
    )
    db.flush()

    assert duplicate is True
    assert same.id == conn.id
    assert db.query(LogbookPersonConnection).count() == 1
    assert same.description == "Updated note."
    assert same.strength == 2
    assert same.confidence == 70
    assert same.status == "suggested"

    update_manual_connection(
        db,
        owner,
        same,
        connection_type="work",
        description="Code project.",
        strength=3,
        confidence=85,
        status="accepted",
        fields_set={"connection_type", "description", "strength", "confidence", "status"},
    )
    db.flush()

    assert same.connection_type == "work"
    assert same.description == "Code project."
    assert same.strength == 3
    assert same.confidence == 85
    assert same.status == "accepted"


def test_manual_connection_update_blocks_duplicate_pair_type():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"

    jan = get_or_create_person(db, owner, "Jan")
    noor = get_or_create_person(db, owner, "Noor")
    db.flush()
    friend, _ = upsert_manual_connection(
        db,
        owner,
        person_a_id=jan.id,
        person_b_id=noor.id,
        connection_type="friend",
    )
    work, _ = upsert_manual_connection(
        db,
        owner,
        person_a_id=jan.id,
        person_b_id=noor.id,
        connection_type="work",
    )
    db.flush()

    with pytest.raises(HTTPException) as exc:
        update_manual_connection(
            db,
            owner,
            work,
            connection_type="friend",
            fields_set={"connection_type"},
        )

    assert friend.connection_type == "friend"
    assert work.connection_type == "work"
    assert exc.value.status_code == 409


def test_person_suggestion_context_is_merged_without_duplicates():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"
    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Daily log",
        content="Nora werkt bij de Buurtmarkt.",
    )
    db.add(entry)
    db.flush()

    suggestion = {
        "display_name": "Nora",
        "surface_text": "Nora",
        "relationship_label": "colleague",
        "notes": "Mentioned in a work context.",
        "llm_context": "Works at Buurtmarkt.",
        "facts": [{
            "fact_type": "workplace",
            "label": "Workplace",
            "value_text": "Buurtmarkt",
            "confidence": 88,
        }],
        "confidence": 88,
    }

    person = link_person_suggestion(db, owner, entry, suggestion)
    link_person_suggestion(db, owner, entry, suggestion)
    db.flush()

    assert person.relationship_label == "colleague"
    assert person.notes == "Mentioned in a work context."
    assert person.llm_context == "Works at Buurtmarkt."
    assert person.llm_context.count("Works at Buurtmarkt.") == 1
    facts = person_facts(db, owner, person.id)
    assert len(facts) == 1
    assert facts[0].fact_type == "workplace"
    assert facts[0].label == "Workplace"
    assert facts[0].value_text == "Buurtmarkt"
    assert facts[0].source_entry_id == "entry-1"
    assert facts[0].source_entry_date == "2026-06-04"
    assert facts[0].last_seen_date == "2026-06-04"
    assert db.query(LogbookPersonFact).count() == 1


def test_manual_person_fact_upsert_deduplicates_same_type_and_value():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"
    person = get_or_create_person(db, owner, "Ava")

    fact, duplicate = upsert_person_fact(
        db,
        owner,
        person,
        fact_type="workplace",
        label="Workplace",
        value_text="Buurtmarkt",
        source="manual",
        confidence=100,
    )
    same_fact, same_duplicate = upsert_person_fact(
        db,
        owner,
        person,
        fact_type="workplace",
        label="Workplace",
        value_text="buurtmarkt",
        source="manual",
        confidence=80,
    )
    db.flush()

    assert duplicate is False
    assert same_duplicate is True
    assert same_fact.id == fact.id
    assert same_fact.source == "manual"
    assert same_fact.confidence == 100
    assert db.query(LogbookPersonFact).count() == 1


def test_merge_person_facts_moves_unique_rows_and_deduplicates_existing_facts():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"
    target = get_or_create_person(db, owner, "Ava")
    source = get_or_create_person(db, owner, "Ava's Sister")
    first_entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-01",
        title="Daily log",
        content="Ava's sister works at Buurtmarkt.",
    )
    later_entry = LogbookEntry(
        id="entry-2",
        owner=owner,
        entry_date="2026-06-03",
        title="Daily log",
        content="Ava works at Buurtmarkt.",
    )
    db.add_all([first_entry, later_entry])
    db.flush()

    upsert_person_fact(
        db,
        owner,
        target,
        fact_type="workplace",
        label="Workplace",
        value_text="Buurtmarkt",
        entry=later_entry,
        confidence=70,
    )
    upsert_person_fact(
        db,
        owner,
        source,
        fact_type="workplace",
        label="Workplace",
        value_text="buurtmarkt",
        entry=first_entry,
        confidence=95,
    )
    upsert_person_fact(
        db,
        owner,
        source,
        fact_type="relationship",
        label="Relationship",
        value_text="Sister",
        entry=first_entry,
        confidence=85,
    )

    result = merge_person_facts(db, owner, source.id, target)
    db.flush()

    assert result == {"moved": 1, "merged": 1}
    assert person_facts(db, owner, source.id) == []
    facts = sorted(person_facts(db, owner, target.id), key=lambda fact: fact.fact_type)
    assert [(fact.fact_type, fact.value_text) for fact in facts] == [
        ("relationship", "Sister"),
        ("workplace", "Buurtmarkt"),
    ]
    workplace = next(fact for fact in facts if fact.fact_type == "workplace")
    assert workplace.confidence == 95
    assert workplace.source_entry_date == "2026-06-01"
    assert workplace.last_seen_date == "2026-06-03"
    assert db.query(LogbookPersonFact).count() == 2


def test_person_facts_for_people_groups_active_facts_with_per_person_limit():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"
    nora = get_or_create_person(db, owner, "Nora")
    milan = get_or_create_person(db, owner, "Milan")
    entry_one = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-01",
        title="Daily log",
        content="Nora werkt bij Buurtmarkt.",
    )
    entry_two = LogbookEntry(
        id="entry-2",
        owner=owner,
        entry_date="2026-06-03",
        title="Daily log",
        content="Nora houdt van thee. Milan werkt bij de bakker.",
    )
    db.add_all([entry_one, entry_two])
    db.flush()

    upsert_person_fact(db, owner, nora, fact_type="workplace", label="Workplace", value_text="Buurtmarkt", entry=entry_one)
    upsert_person_fact(db, owner, nora, fact_type="preference", label="Preference", value_text="Tea", entry=entry_two)
    upsert_person_fact(db, owner, nora, fact_type="note", label="Note", value_text="Old note", entry=entry_two, status="archived")
    upsert_person_fact(db, owner, milan, fact_type="workplace", label="Workplace", value_text="Bakery", entry=entry_two)

    grouped = person_facts_for_people(db, owner, [nora.id, milan.id], limit_per_person=1)

    assert [(fact.fact_type, fact.value_text) for fact in grouped[nora.id]] == [("preference", "Tea")]
    assert [(fact.fact_type, fact.value_text) for fact in grouped[milan.id]] == [("workplace", "Bakery")]


def test_analyze_entry_person_details_only_update_existing_people():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    db = sessionmaker(bind=engine)()
    owner = "owner-1"
    nora = get_or_create_person(db, owner, "Nora")
    entry = LogbookEntry(
        id="entry-1",
        owner=owner,
        entry_date="2026-06-04",
        title="Daily log",
        content="Nora werkt bij de Buurtmarkt. Milan werkt bij de bakker.",
    )
    db.add(entry)
    db.flush()

    updated = store_ai_person_suggestion_details(db, owner, entry, [
        {
            "display_name": "Nora",
            "llm_context": "Works at Buurtmarkt.",
            "facts": [{"fact_type": "workplace", "label": "Workplace", "value_text": "Buurtmarkt", "confidence": 90}],
            "confidence": 90,
        },
        {
            "display_name": "Milan",
            "llm_context": "Works at the bakery.",
            "facts": [{"fact_type": "workplace", "label": "Workplace", "value_text": "Bakery", "confidence": 90}],
            "confidence": 90,
        },
    ])

    assert updated == [nora]
    assert nora.llm_context == "Works at Buurtmarkt."
    facts = person_facts(db, owner, nora.id)
    assert [(fact.fact_type, fact.value_text, fact.source_entry_date, fact.last_seen_date) for fact in facts] == [
        ("workplace", "Buurtmarkt", "2026-06-04", "2026-06-04")
    ]
    assert db.query(LogbookPersonFact).count() == 1
