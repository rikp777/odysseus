from types import SimpleNamespace
from datetime import datetime

import src.logbook.utils as logbook_utils
from src.logbook.ai import normalize_ai_payload
from src.logbook.serializers import entry_to_dict
from src.logbook.utils import canonical_name, parse_locations, parse_mentions


def test_logbook_mention_parser_supports_common_forms():
    mentions = parse_mentions('Talked with @Jan, @"Lisa van Dijk", and @[Ana Maria].')

    assert [m["name"] for m in mentions] == ["Jan", "Lisa van Dijk", "Ana Maria"]
    assert mentions[1]["surface_text"] == '@"Lisa van Dijk"'


def test_logbook_location_parser_supports_common_forms():
    locations = parse_locations('Went to #Gym and #[New York] after work.')

    assert [loc["name"] for loc in locations] == ["Gym", "New York"]


def test_logbook_canonical_name_normalizes_aliases():
    assert canonical_name("@Ján_Peter!") == "jan peter"


def test_logbook_reconnect_suggestion_prefers_meetup_for_social_context(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 4)

    monkeypatch.setattr(logbook_utils, "datetime", FixedDatetime)

    person = {
        "display_name": "Jan",
        "relationship_label": "friend",
        "contact_snapshot": {"emails": ["jan@example.test"]},
    }
    data = logbook_utils.with_stats(person, {"mention_count": 3, "last_mentioned": "2026-04-20"})

    assert data["days_since_mentioned"] == 45
    assert data["reconnect_suggestion"]["suggested_action"] == "meetup"
    assert "Maybe plan a meetup with Jan." in data["reconnect_suggestion"]["message"]


def test_logbook_reconnect_suggestion_stays_quiet_for_recent_mentions(monkeypatch):
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2026, 6, 4)

    monkeypatch.setattr(logbook_utils, "datetime", FixedDatetime)

    person = {"display_name": "Lisa", "relationship_label": "work"}
    data = logbook_utils.with_stats(person, {"mention_count": 1, "last_mentioned": "2026-05-30"})

    assert data["days_since_mentioned"] == 5
    assert data["reconnect_suggestion"] is None


def test_logbook_ai_normalization_keeps_questions_short_and_adds_deterministic_suggestions():
    result = normalize_ai_payload(
        "extract_all",
        {"questions": ["One?", "Two?", "Three?", "Four?"]},
        "Training with @Jan at #Gym.",
    )

    assert result["questions"] == ["One?", "Two?", "Three?"]
    assert result["people_suggestions"][0]["display_name"] == "Jan"
    assert result["location_suggestions"][0]["display_name"] == "Gym"
    assert result["connection_suggestions"] == []


def test_logbook_entry_serializer_counts_unique_people_and_locations():
    person = SimpleNamespace(
        id="p1",
        owner="u1",
        display_name="Jan",
        canonical_name="jan",
        aliases=None,
        notes=None,
        created_at=None,
        updated_at=None,
    )
    location = SimpleNamespace(
        id="l1",
        owner="u1",
        display_name="Gym",
        canonical_name="gym",
        aliases=None,
        notes=None,
        created_at=None,
        updated_at=None,
    )
    entry = SimpleNamespace(
        id="e1",
        owner="u1",
        entry_date="2026-06-04",
        title="Daily log",
        content="Saw @Jan at #Gym.",
        summary=None,
        mood_label=None,
        mood_score=None,
        energy_score=None,
        stress_score=None,
        ai_reflection=None,
        datapoints=[],
        mentions=[
            SimpleNamespace(
                id="m1",
                entry_id="e1",
                person_id="p1",
                surface_text="@Jan",
                start_offset=4,
                end_offset=8,
                source="mention",
                confidence=100,
                created_at=None,
                person=person,
            )
        ],
        location_mentions=[
            SimpleNamespace(
                id="lm1",
                entry_id="e1",
                location_id="l1",
                surface_text="#Gym",
                start_offset=12,
                end_offset=16,
                source="location",
                confidence=100,
                created_at=None,
                location=location,
            )
        ],
        created_at=None,
        updated_at=None,
    )

    data = entry_to_dict(entry)

    assert data["people_count"] == 1
    assert data["location_count"] == 1
    assert data["people"][0]["display_name"] == "Jan"
    assert data["locations"][0]["display_name"] == "Gym"
