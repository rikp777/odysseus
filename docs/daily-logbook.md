# Daily Logbook

Daily Logbook is a local-first journal for one Markdown entry per day. It is built for fast, forgiving daily capture: write messy notes first, then optionally ask the AI to clean spelling, structure the day, ask short follow-up questions, summarize, or extract people, places, mood, and datapoints.

Open it from the app navigation or go directly to `/logbook`.

## Daily Entries

- Today opens by default.
- You can move to yesterday, tomorrow, today, or pick a date.
- Each owner can have one primary entry per date.
- Entries support Markdown content, an optional title, autosave, and a manual save button.
- Meaningful edits keep saved-version history. Use History in the entry editor to preview previous saved versions before restoring one; restore first saves the current entry as another revision.
- The entry header shows an approximate token count for the current day's text, using the same rough character-based estimate used elsewhere for context sizing.
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

People can be created manually, created from mentions, edited, and optionally linked to an existing contact. A Logbook person is not a duplicate contact record; it is journal context that can point at a contact when useful. Person details can include aliases, a relation label selected from common types or typed freely, notes, LLM context, and reconnect settings.

Duplicate people can be merged from the person detail panel in the People & Places atlas. Choose another person and select which record to keep. Mentions, aliases, connections, contact links, and structured facts move to the kept person, while duplicate facts are folded together.

AI person suggestions may also carry explicit stable facts from the entry. For example, if the entry says a person works at Buurtmarkt, the suggestion can save a structured `workplace` fact with `Buurtmarkt` as the value, the source entry id, the first seen date, and the last seen date. The assistant may also add a readable note like `Works at Buurtmarkt.` to that person's LLM context, but the dated fact row is the source of truth.

Person fact types currently include `workplace`, `relationship`, `role`, `location`, `preference`, `note`, and `unknown`. Facts can be added manually from the person detail panel in the People & Places atlas. Facts are de-duplicated by person, type, and value; if the same fact appears again later, the last seen date is updated.

Person cards and Atlas detail panels show compact connection summaries when the Logbook has accepted or suggested relationships for that person. Suggested connections stay reviewable; hidden suggestions are kept out of normal cards and lists.

Places can also be created manually or from `#place` mentions. They can store address text, type, notes, aliases, LLM context, and an optional advanced map pin. Duplicate place names and aliases open the existing place instead of creating another row.

Unused places with zero linked entries can be deleted from the atlas. Places with existing entry history should be hidden instead: hidden places stay in history, but they are removed from linking, autocomplete, and the map until they are unhidden.

## Map

The Logbook atlas uses the shared frontend map helper in `static/js/maps.js`. The map is generic so other features can reuse it later.

The current map is local and dependency-light by default. Place editing is address-first; latitude and longitude are treated as optional advanced pin data. The map plots places with saved pins and lists address-only places separately. It does not call external geocoding or map tile APIs unless you explicitly enable a geocoder or tile provider; outbound map search links only open when the user clicks them.

Docker deployments can optionally run a local Photon geocoder for privacy-preserving address lookup:

```bash
docker compose --profile geocoder up -d --build geocoder
```

The optional profile binds Photon to `127.0.0.1:2322` by default and stores the downloaded database in the `geocoder-photon-data` volume. The default dataset is the Netherlands extract; set `PHOTON_DB_URL` in `.env` to use another Photon country or region dump.

When `LOGBOOK_GEOCODER_URL` is configured, the place editor can find coordinates from a typed address through the Odysseus backend. Results are applied only after the user selects a candidate.

For low-RAM installs, `LOGBOOK_GEOCODER_PROVIDER=nominatim` can use the public Nominatim API instead of a local Photon database. This is an explicit privacy tradeoff because typed addresses leave the server. Use it only for manual, user-triggered lookups; Odysseus caches repeated queries and throttles public Nominatim calls to respect the public service limits.

To show map imagery behind saved pins, set `LOGBOOK_MAP_TILE_PROVIDER=satellite`
or provide `LOGBOOK_MAP_TILE_URL` with a `{z}/{x}/{y}` slippy-map template. This
is also an explicit privacy tradeoff: the browser requests tiles for the visible
map area from that provider. Leave it blank to keep the local pin grid.

## AI Help

The AI endpoints use the configured Odysseus model endpoints only. Manual journaling still works if AI is unavailable.

AI modes include:

- Clean spelling while preserving the user's voice.
- Turn messy notes into a readable daily log.
- Ask up to three short questions.
- Summarize a saved day.
- Extract people, places, mood, datapoints, and possible connections.
- Extract stable person facts from a saved day and save them to existing people.
- Reflect gently without giving medical or therapy advice.

The general assistant can also use the Logbook tool to read owner-scoped daily entries and atlas context. When it references something from the Logbook, it should cite the relevant date instead of treating memory as unsupported fact.

## Connections And Reconnect Hints

When two people are mentioned in the same entry, Logbook can suggest a possible connection with evidence from the dated entry. Suggestions stay cautious until the user accepts them, and hidden suggestions remain hidden unless there is substantial new evidence.

Connections can also be created or edited manually from the Atlas Connections tab. Manual connections use the same person records and relationship types as AI suggestions, but they default to accepted because the user created them directly.

Reconnect hints are based on the last Logbook mention and optional person context. For example, the atlas may suggest that it could be a good time to message or meet someone if they have not appeared in entries for a while. This is only based on journal evidence, not proof of real-world contact.

## Privacy And Limits

- Rows are owner-scoped.
- Private entry content is not logged as full prompts or responses.
- No external map or geocoding APIs are called automatically by the map helper.
- Place map pins are optional and can be added manually when needed.
- Contact linking is optional and keeps contacts as the source of contact details.
