from types import SimpleNamespace
from datetime import datetime

import pytest

import src.logbook.utils as logbook_utils
from fastapi import HTTPException

from src.logbook.ai import estimate_ai_usage, local_ai_fallback_payload, normalize_ai_payload, run_ai_assist
from src.logbook.schemas import LogbookAIAssist, LogbookApplySuggestions
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


def test_logbook_apply_suggestions_accepts_normalized_confidence():
    payload = LogbookApplySuggestions.model_validate({
        "people_suggestions": [{
            "display_name": "Jan",
            "confidence": 0.9,
            "facts": [{
                "fact_type": "relationship",
                "label": "Relationship",
                "value_text": "Father",
                "confidence": 0.8,
            }],
        }],
        "location_suggestions": [{
            "display_name": "Meerstad",
            "confidence": 0.75,
        }],
    })

    assert payload.people_suggestions[0].confidence == 0.9
    assert payload.people_suggestions[0].facts[0].confidence == 0.8
    assert payload.location_suggestions[0].confidence == 0.75


def test_logbook_clamp_confidence_supports_decimal_and_percent_inputs():
    assert logbook_utils.clamp_confidence(0.9, default=70) == 90
    assert logbook_utils.clamp_confidence("0.75", default=70) == 75
    assert logbook_utils.clamp_confidence(90, default=70) == 90


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


def test_logbook_local_ai_fallback_adds_workplace_context_to_person_suggestion():
    result = local_ai_fallback_payload(
        "extract_all",
        "Ava werkt bij de buurtmarkt. Later dronk de tester thee met haar.",
        owner="tester",
    )

    ava = next(item for item in result["people_suggestions"] if item["display_name"] == "Ava")

    assert ava["reason"] == "Fallback workplace hint"
    assert ava["llm_context"] == "Works at Buurtmarkt."
    assert ava["facts"] == [{
        "fact_type": "workplace",
        "label": "Workplace",
        "value_text": "Buurtmarkt",
        "confidence": 74,
        "reason": "Fallback workplace hint",
    }]


def test_logbook_local_ai_fallback_adds_workplace_fact_for_linked_person():
    result = local_ai_fallback_payload(
        "structure_day",
        "[Ava](person:ava) werkt bij de buurtmarkt. Later dronk de tester thee met haar.",
        owner="tester",
    )

    ava = next(item for item in result["people_suggestions"] if item["display_name"] == "Ava")

    assert ava["llm_context"] == "Works at Buurtmarkt."
    assert ava["facts"][0]["fact_type"] == "workplace"
    assert ava["facts"][0]["value_text"] == "Buurtmarkt"


def test_logbook_ai_normalization_merges_local_workplace_fact_into_model_person():
    result = normalize_ai_payload(
        "structure_day",
        {
            "preview_content": "[Ava](person:ava) works at Buurtmarkt.",
            "people_suggestions": [{"display_name": "Ava", "confidence": 80, "reason": "Model person"}],
        },
        "[Ava](person:ava) werkt bij de buurtmarkt.",
        owner="tester",
    )

    ava = next(item for item in result["people_suggestions"] if item["display_name"] == "Ava")

    assert ava["confidence"] == 80
    assert ava["llm_context"] == "Works at Buurtmarkt."
    assert ava["facts"] == [{
        "fact_type": "workplace",
        "label": "Workplace",
        "value_text": "Buurtmarkt",
        "confidence": 74,
        "reason": "Fallback workplace hint",
    }]


def test_logbook_local_ai_fallback_resolves_sister_workplace_to_named_person():
    content = (
        "Ik ben even naar de Buurtmarkt gereden waar mijn zus aan het werken was. "
        "Nadat ik wakker werd, was \nLina\n   klaar met werken en had ze lekker gekookt."
    )

    result = local_ai_fallback_payload("structure_day", content, owner="tester")
    lina = next(item for item in result["people_suggestions"] if item["display_name"] == "Lina")

    assert lina["relationship_label"] == "family"
    assert lina["llm_context"] == "Works at Buurtmarkt."
    assert {"fact_type": "relationship", "label": "Relationship", "value_text": "Sister", "confidence": 70, "reason": "Fallback relation hint"} in lina["facts"]
    assert {"fact_type": "workplace", "label": "Workplace", "value_text": "Buurtmarkt", "confidence": 72, "reason": "Fallback relation workplace hint"} in lina["facts"]


def test_logbook_ai_normalization_merges_sister_workplace_fact_when_model_misses_it():
    content = (
        "Ik ben even naar de Buurtmarkt gereden waar mijn zus aan het werken was. "
        "Nadat ik wakker werd, was \nLina\n   klaar met werken en had ze lekker gekookt."
    )

    result = normalize_ai_payload(
        "structure_day",
        {
            "preview_content": content,
            "people_suggestions": [{"display_name": "Lina", "confidence": 82, "reason": "Model person"}],
        },
        content,
        owner="tester",
    )
    lina = next(item for item in result["people_suggestions"] if item["display_name"] == "Lina")

    assert lina["confidence"] == 82
    assert lina["relationship_label"] == "family"
    assert any(fact["fact_type"] == "workplace" and fact["value_text"] == "Buurtmarkt" for fact in lina["facts"])


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
    assert call_kwargs["return_usage"] is True
    assert call_kwargs["billing_context"]["source"] == "logbook_ai:extract_all"
    assert result["usage"]["fallback"] is True
    assert result["usage"]["actual"]["total_tokens"] == 0
    assert result["usage"]["estimate"]["input_tokens"] > 0
    assert result["people_suggestions"][0]["display_name"] == "Milan de Vries"
    assert result["location_suggestions"][0]["display_name"] == "Meerstad"
    assert "[Milan de Vries](person:milan_de_vries)" in result["preview_content"]


def test_logbook_ai_estimate_includes_cost_and_scoped_summaries(monkeypatch):
    import src.endpoint_resolver as endpoint_resolver
    from src import billing_usage

    seen = []
    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda *_args, **_kwargs: ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", {}))

    def fake_usage_summary(*, period="month", owner=None, source_prefix=None, now=None):
        seen.append((period, owner, source_prefix))
        return {
            "enabled": True,
            "period": period,
            "amount_decimal": "0.01",
            "projected_decimal": "0.02",
            "amount": "0.010000",
            "display": "$0.01",
            "events": 1,
            "input_tokens": 10,
            "output_tokens": 5,
            "total_tokens": 15,
            "providers": [],
            "models": [],
        }

    monkeypatch.setattr(billing_usage, "get_usage_summary", fake_usage_summary)

    result = estimate_ai_usage(
        "alex",
        LogbookAIAssist(
            entry_date="2099-01-02",
            mode="summarize",
            locale="en",
            content="A short day with notes.",
        ),
    )

    assert result["available"] is True
    assert result["model"] == "gpt-4o-mini"
    assert result["estimate"]["input_tokens"] > 0
    assert result["estimate"]["max_output_tokens"] == 1600
    assert result["estimate"]["cost"]["known"] is True
    assert "amount_decimal" not in result["day"]
    assert seen == [
        ("day", "alex", "logbook_ai"),
        ("month", "alex", "logbook_ai"),
    ]


@pytest.mark.asyncio
async def test_logbook_ai_assist_returns_actual_usage_metadata(monkeypatch):
    import src.endpoint_resolver as endpoint_resolver
    import src.llm_core as llm_core
    from src import billing_usage

    call_kwargs = {}

    async def usage_call(**kwargs):
        call_kwargs.update(kwargs)
        return {
            "text": '{"ok": true, "summary": "Done."}',
            "usage": {
                "input_tokens": 42,
                "output_tokens": 9,
                "model": "gpt-4o-mini",
                "usage_source": "real",
            },
            "endpoint_url": "https://api.openai.com/v1/chat/completions",
            "model": "gpt-4o-mini",
            "provider": "openai",
            "cached": False,
            "recorded": True,
        }

    monkeypatch.setattr(endpoint_resolver, "resolve_endpoint", lambda *_args, **_kwargs: ("https://api.openai.com/v1/chat/completions", "gpt-4o-mini", {}))
    monkeypatch.setattr(llm_core, "llm_call_async", usage_call)
    monkeypatch.setattr(
        billing_usage,
        "get_usage_summary",
        lambda *, period="month", owner=None, source_prefix=None, now=None: {
            "enabled": True,
            "period": period,
            "amount": "0.001000",
            "display": "$0.0010",
            "events": 1,
            "input_tokens": 42,
            "output_tokens": 9,
            "total_tokens": 51,
            "providers": [],
            "models": [],
        },
    )

    result = await run_ai_assist(
        "alex",
        LogbookAIAssist(
            entry_date="2099-01-02",
            mode="summarize",
            locale="en",
            content="Alex wrote enough to summarize.",
        ),
    )

    assert result["summary"] == "Done."
    assert call_kwargs["return_usage"] is True
    assert call_kwargs["billing_context"]["source"] == "logbook_ai:summarize"
    assert result["usage"]["fallback"] is False
    assert result["usage"]["recorded"] is True
    assert result["usage"]["actual"]["input_tokens"] == 42
    assert result["usage"]["actual"]["output_tokens"] == 9
    assert result["usage"]["actual"]["total_tokens"] == 51
    assert result["usage"]["actual"]["cost"]["known"] is True
    assert result["usage"]["day"]["total_tokens"] == 51


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
