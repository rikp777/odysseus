# Custom Branch Notes

This folder documents the personal `custom` branch. It is intentionally safe to
commit: no passwords, API keys, SSH details, hostnames, IP addresses, private
account IDs, or personal recovery information should be added here.

Detailed deployment notes that include private infrastructure details stay in
`.personal/`, which is ignored by Git.

## Why This Branch Exists

This branch is used as a personal Odysseus build for a private, always-on
workspace. The upstream project moves carefully on large feature additions, and
some of these changes are personal-product decisions rather than upstream-ready
work. Keeping them on `custom` lets the personal deployment move forward while
still keeping the work reviewed, documented, committed, and easy to compare
against upstream.

The main goals are:

- keep private data behind a VPN/tailnet-only deployment;
- make model spending visible before and after requests;
- make cloud model usage safer with soft warnings and hard app-side limits;
- improve the Daily Logbook into a richer personal knowledge tool;
- keep custom code modular enough that upstream changes can still be merged.

## Deployment Shape

The production deployment runs the `custom` branch in Docker Compose behind a
private network route/reverse proxy. Odysseus itself stays bound to localhost
inside the host, and browser access is intended to go through a trusted private
network rather than direct public exposure.

Production-specific values such as the exact machine, DNS, SSH command, admin
password location, model tokens, billing tokens, and account identifiers are not
documented here.

## Current Custom Changes

For the upstream sync strategy and fork health checklist, see
[`upstream-maintenance-plan.md`](./upstream-maintenance-plan.md).

For day-to-day rules on where custom code lives and how to add new custom work,
see [`working-guide.md`](./working-guide.md).

### Cloud Spend And Model Pricing

Odysseus has a custom Cloud Spend area in Settings. It can show current AI model
spend, provider model-billing totals where available, local usage-ledger totals,
and provider account health. The navbar/sidebar can show the month-to-date AI
spend when billing is configured.

Why:

- prevent accidental expensive cloud-model use;
- make model costs visible near model selection;
- separate AI/model spend from unrelated cloud infrastructure spend;
- support multiple billing providers/accounts over time instead of hard-coding a
  single provider.

Important design points:

- billing support is optional and stays collapsed/quiet until configured;
- provider adapters are separated from route/UI code;
- local usage events provide a fallback ledger when provider model-billing is
  unavailable;
- external account totals are treated as audit/context data, not the AI spend
  total used by the main UI.

### Spending Limits And Graphs

The custom build adds warning and limit controls for monthly and daily AI spend,
plus graph views for usage. Graphs support interactive hover details, optional
projection lines, month navigation, and toggles for warning/limit reference
lines.

Why:

- spending needs to be visible as a timeline, not only a single number;
- warnings and hard limits should be understandable before a model call happens;
- the graph should make derived data inspectable without cluttering the default
  UI.

### Added Models Pricing

The Added Models/Endpoints list can show pricing when billing/pricing data is
available. Model lists can be sorted by cheapest, most expensive, or estimated
intelligence.

Why:

- selecting a model should include cost awareness;
- expensive models should be harder to choose accidentally;
- pricing belongs close to provider/model management, not only after a request.

### Daily Logbook Editor

The Daily Logbook now defaults to a richer editor experience while still keeping
a raw Markdown option. Selected text can be linked as a person, place, or food
entity, and existing links can be removed.

Why:

- personal journaling should not require editing raw mention syntax all the
  time;
- raw Markdown remains available for power users and debugging;
- linking entities should be explicit so the logbook does not silently create
  unwanted personal data.

### Logbook Entity Hover Cards

Linked people, places, and food/data entities can show hover info in the editor.
For example, hovering a linked person can surface the known person details.

Why:

- linked entities should be inspectable in context;
- users should not have to leave the entry to check what a linked person/place
  means;
- this makes entity linking feel like part of the editor rather than a separate
  database screen.

### Place Management

Places now have stronger lifecycle rules:

- duplicate places are blocked, including duplicates of hidden places;
- places with no linked entries can be deleted;
- places with linked history can be hidden instead of deleted;
- hidden places no longer appear in normal linking/autocomplete/map flows;
- hidden places can be unhidden from the Atlas UI.

Why:

- personal location data should not fragment into duplicates;
- deleting historical linked data would be risky;
- hiding gives a safer way to retire a place without losing old journal context.

### Logbook Atlas And Map Work

The custom build expands the Logbook Atlas with richer people/place management,
map support, shared icons, and clearer entity controls.

Why:

- the logbook is becoming a personal memory surface, not just a dated note list;
- people, places, and relationships need management views;
- icons and shared frontend modules make the UI more consistent and easier to
  maintain.

## Maintainability Rules For Custom Work

Custom code should still follow the main project style:

- use `custom/` as the control plane for custom registration and docs;
- prefer small provider/service modules over large route-file blobs;
- register custom frontend assets through `custom/frontend_assets.py`;
- keep billing provider logic behind adapters/factories;
- keep UI modules split where the upstream already has a split-module pattern;
- add tests around repository and billing behavior when data rules change;
- avoid private deployment assumptions in reusable code;
- keep generated screenshots, personal scripts, and private notes out of Git
  unless they are sanitized documentation assets.

## What Stays Private

The following must stay in `.personal/`, local env files, encrypted app storage,
or the production machine:

- SSH commands and key paths;
- server IPs and private DNS choices;
- admin usernames/passwords or password file paths;
- API keys and billing tokens;
- raw billing account IDs;
- exact production firewall details;
- personal screenshots or data exports that reveal private content.

