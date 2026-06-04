"""Pydantic request models for Daily Logbook routes."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel


ALLOWED_CONNECTION_TYPES = {"co_mentioned", "family", "friend", "work", "training", "conflict", "unknown"}
ALLOWED_CONNECTION_STATUS = {"suggested", "accepted", "hidden"}
AI_MODES = {
    "clean_spelling",
    "structure_day",
    "summarize",
    "ask_questions",
    "extract_people",
    "extract_locations",
    "reflect",
    "extract_all",
}


class LogbookDataPointIn(BaseModel):
    id: Optional[str] = None
    key: str = ""
    label: Optional[str] = None
    value_text: Optional[str] = None
    value_number: Optional[float] = None
    unit: Optional[str] = None
    value_json: Optional[Any] = None
    sort_order: Optional[int] = None


class LogbookEntryUpsert(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    mood_label: Optional[str] = None
    mood_score: Optional[int] = None
    energy_score: Optional[int] = None
    stress_score: Optional[int] = None
    datapoints: Optional[List[LogbookDataPointIn]] = None


class LogbookEntryUpdate(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    summary: Optional[str] = None
    mood_label: Optional[str] = None
    mood_score: Optional[int] = None
    energy_score: Optional[int] = None
    stress_score: Optional[int] = None
    ai_reflection: Optional[str] = None
    datapoints: Optional[List[LogbookDataPointIn]] = None


class LogbookPersonCreate(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    relationship_label: Optional[str] = None
    llm_context: Optional[str] = None
    contact_uid: Optional[str] = None


class LogbookPersonUpdate(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    relationship_label: Optional[str] = None
    llm_context: Optional[str] = None
    contact_uid: Optional[str] = None
    contact_source: Optional[str] = None
    contact_snapshot_json: Optional[Any] = None


class LogbookPersonContactLink(BaseModel):
    contact_uid: str


class LogbookPeopleMerge(BaseModel):
    source_person_id: str
    target_person_id: str


class LogbookLocationCreate(BaseModel):
    display_name: str
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: Optional[str] = None
    llm_context: Optional[str] = None


class LogbookLocationUpdate(BaseModel):
    display_name: Optional[str] = None
    aliases: Optional[List[str]] = None
    notes: Optional[str] = None
    hidden: Optional[bool] = None
    address: Optional[str] = None
    latitude: Optional[float] = None
    longitude: Optional[float] = None
    location_type: Optional[str] = None
    llm_context: Optional[str] = None


class LogbookLocationsMerge(BaseModel):
    source_location_id: str
    target_location_id: str


class LogbookEntitySuggestion(BaseModel):
    display_name: Optional[str] = None
    surface_text: Optional[str] = None
    aliases: Optional[List[str]] = None
    confidence: Optional[int] = None
    reason: Optional[str] = None


class LogbookApplySuggestions(BaseModel):
    people_suggestions: Optional[List[LogbookEntitySuggestion]] = None
    location_suggestions: Optional[List[LogbookEntitySuggestion]] = None


class LogbookAIAssist(BaseModel):
    entry_date: str
    content: str = ""
    mode: str
    locale: str = "en"
    current_entry: Optional[Dict[str, Any]] = None
