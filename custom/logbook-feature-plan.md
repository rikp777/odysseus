# Daily Logbook Feature Plan

## Current Strength

The Logbook already has a strong base: daily entries, structured datapoints,
people, places, contact linking, revisions, AI assist, relationship connections,
and Atlas views. The next features should build on those existing primitives
instead of adding another disconnected journaling surface.

## Product Direction

Make Logbook useful as a personal operating memory:

- Capture messy daily notes quickly.
- Turn entries into reviewable structure.
- Surface patterns across mood, energy, sleep, places, people, and routines.
- Help the user remember people and follow up without overstating AI guesses.
- Answer natural language recall questions with dated evidence.

## Recommended First Milestone: Review Dashboard

Build a "Review" tab inside the existing Logbook modal.

Backend:

- Add a read-only review endpoint for a date range, starting with week and month.
- Reuse `src.logbook.repository.entry_query`, person/location stats, and serializers.
- Return highlights, mood counts, datapoint series, top people, top places, reconnect candidates, and notable entry snippets.
- Keep AI optional: deterministic summary first, AI-written reflection only when the provider is available.

Frontend:

- Add a compact Review tab next to Write, Entries, People, Places, and AI.
- Show weekly/monthly sections: mood trend, energy/stress/sleep datapoints, people seen, places visited, and open reconnect prompts.
- Use existing Logbook CSS/components; avoid a separate dashboard style.

Tests:

- Repository-level test for review aggregation.
- Route test for owner scoping and date range limits.
- JS syntax and a small rendering test for empty vs populated review payloads.

Why first: it uses existing data, gives immediate value, and creates the API shape needed by later insights.

## Phase 2: Insight Cards

Add reusable insight cards generated from structured data:

- "Energy is lower after short sleep" style correlations.
- Mood streaks and outliers.
- Frequent people/places this week compared with prior weeks.
- Missing datapoint reminders, for example when sleep is usually tracked but absent today.
- "Worth remembering" candidates from repeated facts or locations.

Keep every insight explainable with dates and source entries.

## Phase 3: People Follow-Up Cockpit

Extend the existing people and connection work:

- Add a reconnect inbox with suggested action, reason, last mentioned date, and contact method.
- Add dismiss/snooze state so the same suggestion does not keep returning.
- Separate accepted relationships from suggested relationships visually and in API responses.
- Add filters for family, work, friends, training, and stale contacts.

This should use current person stats and contact snapshots rather than introducing a new contacts model.

First implementation slice:

- A read-only follow-up inbox now derives active prompts from person stats.
- Person-level snooze, dismiss, and restore actions suppress repeated prompts.
- Follow-up cards show last mention, days stale, relationship, contact method, and accepted/suggested connection counts.

## Phase 4: Better Recall

Improve chat/tool recall without making Logbook writes implicit:

- Add richer `manage_logbook` actions for weekly review, monthly review, and trend lookup.
- Add a citation-first answer format for natural language recall: date, entry snippet, people, places, datapoints.
- Optional semantic search can come later, but the first version should remain SQL/date/filter based for predictable behavior.

## Phase 5: Faster Capture

After review/insights are solid, improve input speed:

- Quick capture command from anywhere in the app.
- Entry templates for workout, illness, workday, travel, and social day.
- Voice note transcription as an optional local/remote AI action.
- Attachment support for photos or files linked to a day, person, or place.

## Guardrails

- Do not auto-create facts or relationships without review when confidence is low.
- Do not mix suggested connections with accepted facts in chat context.
- Keep owner scoping explicit in every route and repository helper.
- Prefer reusable Logbook repository/utils modules over new route-local helpers.
- Keep custom feature wiring inside `custom/` and static custom modules.
