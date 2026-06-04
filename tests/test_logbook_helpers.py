from types import SimpleNamespace
from datetime import datetime

import pytest

import src.logbook.utils as logbook_utils
from fastapi import HTTPException

from src.logbook.ai import local_ai_fallback_payload, normalize_ai_payload, run_ai_assist
from src.logbook.schemas import LogbookAIAssist
from src.logbook.serializers import entry_to_dict
from src.logbook.utils import (
    canonical_name,
    known_entity_matches,
    parse_data_links,
    parse_location_links,
    parse_locations,
    parse_mentions,
    parse_person_links,
)


def test_logbook_mention_parser_supports_common_forms():
    mentions = parse_mentions('Talked with @Jan, @"Lisa van Dijk", and @[Ana Maria].')

    assert [m["name"] for m in mentions] == ["Jan", "Lisa van Dijk", "Ana Maria"]
    assert mentions[1]["surface_text"] == '@"Lisa van Dijk"'


def test_logbook_location_parser_supports_common_forms():
    locations = parse_locations('Went to #Gym and #[New York] after work.')

    assert [loc["name"] for loc in locations] == ["Gym", "New York"]


def test_logbook_canonical_name_normalizes_aliases():
    assert canonical_name("@Ján_Peter!") == "jan peter"
    assert canonical_name("person:jeanine_peeters") == "jeanine peeters"
    assert canonical_name("place:ouderlijk_huis") == "ouderlijk huis"


def test_logbook_person_link_parser_supports_custom_markdown():
    links = parse_person_links("Thee met [Nora](person:nora_smit) en [Mila](mila_jansen).")

    assert [(link["name"], link["target_name"], link["target_slug"]) for link in links] == [
        ("Nora", "nora smit", "nora_smit"),
        ("Mila", "mila jansen", "mila_jansen"),
    ]


def test_logbook_location_link_parser_supports_custom_markdown():
    links = parse_location_links("Thuis in [Meerstad](place:meerstad), later bij [studio](location:studio_noord).")

    assert [(link["name"], link["target_name"], link["target_slug"]) for link in links] == [
        ("Meerstad", "meerstad", "meerstad"),
        ("studio", "studio noord", "studio_noord"),
    ]


def test_logbook_data_link_parser_supports_food_datapoints():
    links = parse_data_links("Ontbijt was [eiwitrijk ontbijt](data:food) en [thee](food:thee).")

    assert [(link["key"], link["label"], link["value_text"]) for link in links] == [
        ("food", "Food", "eiwitrijk ontbijt"),
        ("food", "Food", "thee"),
    ]


def test_logbook_known_entity_matches_normal_text_without_marker():
    milan = SimpleNamespace(id="p1", display_name="Milan de Vries", aliases='["Milan"]')
    noor = SimpleNamespace(id="p2", display_name="Noor", aliases=None)

    matches = known_entity_matches(
        "Alex zag Milan de Vries en Noor in Meerstad. @Milan telt niet dubbel.",
        [milan, noor],
    )

    assert [(m["row"].id, m["surface_text"]) for m in matches] == [
        ("p1", "Milan de Vries"),
        ("p2", "Noor"),
    ]

    blocked = known_entity_matches(
        "Alex zag [Milan de Vries](person:milan_de_vries).",
        [milan],
        blocked_ranges=[(8, 55)],
    )
    assert blocked == []


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
        "Training with @Jan at #Gym. Ontbijt: [eiwitrijk ontbijt](data:food). Later in [Meerstad](place:meerstad).",
    )

    assert result["questions"] == ["One?", "Two?", "Three?"]
    assert result["people_suggestions"][0]["display_name"] == "Jan"
    assert [item["display_name"] for item in result["location_suggestions"]] == ["Meerstad", "Gym"]
    assert result["datapoint_suggestions"][0]["key"] == "food"
    assert result["connection_suggestions"] == []


def test_logbook_local_ai_fallback_extracts_obvious_dutch_prose_hints():
    content = (
        "Alex stond vroeg op in zijn ouderlijk huis in Meerstad. Na een eiwitrijk ontbijt - uiteraard zonder suiker - "
        "stapte hij op de fiets. In de keuken trof hij zijn ouders, Nora en Sam, die al bezig waren met de dagelijkse routine.\n\n"
        "Daar kwam hij onverwacht Milan de Vries tegen.\n\n"
        "Tegen de middag fietste hij door naar zijn oma, Lena Jansen. Ze dronken samen een kop thee.\n\n"
        "Bij terugkomst thuis trof hij zijn zus, Tess Bakker, in de tuin. Hij sloot de dag af met een voldaan gevoel."
    )

    result = local_ai_fallback_payload(
        "extract_all",
        content,
        owner="alex",
        warning="AI provider timed out; showing local suggestions only.",
    )

    people = {item["display_name"] for item in result["people_suggestions"]}
    locations = {item["display_name"] for item in result["location_suggestions"]}
    datapoints = {(item["key"], item["value_text"]) for item in result["datapoint_suggestions"]}

    assert result["fallback"] is True
    assert "timed out" in result["warning"]
    assert "Alex" not in people
    assert "In de" not in people
    assert "Tegen de" not in people
    assert {"Nora", "Sam", "Milan de Vries", "Lena Jansen", "Tess Bakker"} <= people
    assert {"Meerstad", "Ouderlijk huis", "Centrum", "Thuis", "Tuin"} & locations
    assert ("food", "eiwitrijk ontbijt") in datapoints
    assert ("nutrition", "zonder suiker") in datapoints
    assert ("drink", "thee") in datapoints
    assert result["mood_suggestion"]["label"] == "voldaan"
    assert "[Milan de Vries](person:milan_de_vries)" in result["preview_content"]
    assert "[Meerstad](place:meerstad)" in result["preview_content"]
    assert "[eiwitrijk ontbijt](data:food)" in result["preview_content"]


@pytest.mark.parametrize("status_code", [404, 504])
@pytest.mark.asyncio
async def test_logbook_ai_assist_returns_local_fallback_on_provider_error(monkeypatch, status_code):
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core

    call_kwargs = {}

    async def timeout_call(**kwargs):
        call_kwargs.update(kwargs)
        raise HTTPException(status_code, "Provider failure")

    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda *_args, **_kwargs: ("https://llm.example", "model", {}))
    monkeypatch.setattr(llm_core, "llm_call_async", timeout_call)

    result = await run_ai_assist(
        "alex",
        LogbookAIAssist(
            entry_date="2099-01-02",
            mode="extract_all",
            locale="nl",
            content="Alex zag Milan de Vries in Meerstad na een eiwitrijk ontbijt.",
        ),
    )

    assert result["ok"] is True
    assert result["fallback"] is True
    assert str(status_code) in result["warning"]
    assert call_kwargs["timeout"] == 25
    assert call_kwargs["max_retries"] == 2
    assert result["people_suggestions"][0]["display_name"] == "Milan de Vries"
    assert result["location_suggestions"][0]["display_name"] == "Meerstad"
    assert "[Milan de Vries](person:milan_de_vries)" in result["preview_content"]


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
