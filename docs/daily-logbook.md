# Daily Logbook

Daily Logbook is a local-first journal for one Markdown entry per day. It is built for fast, forgiving daily capture: write messy notes first, then optionally ask the AI to clean spelling, structure the day, ask short follow-up questions, summarize, or extract people, places, mood, and datapoints.

Open it from the app navigation or go directly to `/logbook`.

## Daily Entries

- Today opens by default.
- You can move to yesterday, tomorrow, today, or pick a date.
- Each owner can have one primary entry per date.
- Entries support Markdown content, an optional title, autosave, and a manual save button.
- AI suggestions are preview-first. They do not overwrite the entry until you apply them.

## Mood And Datapoints

Mood is optional. You can skip it completely or add a label and simple 1-5 scores for mood, energy, and stress.

Datapoints are flexible structured rows for things like sleep, workout, pain, food, medication, gratitude, work, or social notes. Each datapoint can have a label, text value, optional number, optional unit, and future JSON data. They are stored outside the Markdown entry so later charts and statistics can use them.

## People And Places

Daily Logbook extracts context from explicit links and mentions:

- In the rich editor, select text and use the Person, Place, or Food actions to turn it into a linked token.
- Use Unlink to turn a linked token back into normal text.
- Plain names are left as plain text. This keeps unlinking intentional and prevents known people or places from being recreated automatically after autosave.
- `@Jan` creates or links a Logbook person.
- `#Amsterdam` creates or links a Logbook place.
- `[Jan](person:jan)` and `[Amsterdam](place:amsterdam)` are the raw Markdown forms used by the editor.
- Known people and places show up in autocomplete while writing.
- Mentions remain linked to the day they came from.

The People & Places atlas is available at `/logbook/atlas`. It has tabs for People, Locations, Map, and Connections.

People can be created manually, created from mentions, edited, and optionally linked to an existing contact. A Logbook person is not a duplicate contact record; it is journal context that can point at a contact when useful. Person details can include aliases, relationship, notes, LLM context, and reconnect settings.

Places can also be created manually or from `#place` mentions. They can store address text, notes, aliases, LLM context, and optional latitude/longitude. Duplicate place names and aliases open the existing place instead of creating another row.

Unused places with zero linked entries can be deleted from the atlas. Places with existing entry history should be hidden instead: hidden places stay in history, but they are removed from linking, autocomplete, and the map until they are unhidden.

## Map

The Logbook atlas uses the shared frontend map helper in `static/js/maps.js`. The map is generic so other features can reuse it later.

The current map is local and dependency-light. It plots places with saved latitude and longitude and provides search links for places that do not have coordinates yet. It does not call external geocoding or map tile APIs.

## AI Help

The AI endpoints use the configured Odysseus model endpoints only. Manual journaling still works if AI is unavailable.

AI modes include:

- Clean spelling while preserving the user's voice.
- Turn messy notes into a readable daily log.
- Ask up to three short questions.
- Summarize a saved day.
- Extract people, places, mood, datapoints, and possible connections.
- Reflect gently without giving medical or therapy advice.

The general assistant can also use the Logbook tool to read owner-scoped daily entries and atlas context. When it references something from the Logbook, it should cite the relevant date instead of treating memory as unsupported fact.

## Connections And Reconnect Hints

When two people are mentioned in the same entry, Logbook can suggest a possible connection with evidence from the dated entry. Suggestions stay cautious until the user accepts them, and hidden suggestions remain hidden unless there is substantial new evidence.

Reconnect hints are based on the last Logbook mention and optional person context. For example, the atlas may suggest that it could be a good time to message or meet someone if they have not appeared in entries for a while. This is only based on journal evidence, not proof of real-world contact.

## Privacy And Limits

- Rows are owner-scoped.
- Private entry content is not logged as full prompts or responses.
- No external map or geocoding APIs are used by the map helper.
- Place coordinates must be added manually for now.
- Contact linking is optional and keeps contacts as the source of contact details.
