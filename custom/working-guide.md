# Custom Branch Working Guide

## Core Rule

`upstream/main` is the source of truth. The `custom` branch is an overlay.

Custom code should depend on upstream code. Upstream/shared code should only
have small, explicit hooks into custom code. If a change makes a shared file
own personal behavior, move that behavior behind a custom registry, bootstrap,
service, or frontend module.

## What Belongs In `custom/`

The `custom/` folder is the control plane for personal features:

- docs and rules for the custom branch;
- backend feature registration;
- frontend asset registration;
- custom-only route/page registration;
- small registries that keep custom entries out of upstream-owned maps.

Current files:

- `custom/README.md`: branch overview and feature summary.
- `custom/upstream-maintenance-plan.md`: upstream sync and merge discipline.
- `custom/working-guide.md`: this guide.
- `custom/bootstrap.py`: registers custom backend routers and SPA routes.
- `custom/frontend_assets.py`: registers custom CSS and JS assets injected into
  the shared HTML shell.

Do not put private deployment details, secrets, account IDs, SSH commands,
production hostnames, or personal raw data in `custom/`.

## Where Custom Code Lives

Custom ownership does not mean every file physically lives inside `custom/`.
Runtime files should stay where the app naturally serves or imports them.

| Area | Control Point | Runtime Files |
| --- | --- | --- |
| Backend route registration | `custom/bootstrap.py` | `routes/billing_routes.py`, `routes/logbook_routes.py` |
| Frontend asset registration | `custom/frontend_assets.py` | `static/css/*`, `static/js/custom/*` |
| Billing domain logic | `custom/bootstrap.py` for route registration | `src/billing/*`, `src/billing_usage.py`, `routes/billing_routes.py` |
| Logbook domain logic | `custom/bootstrap.py` for route registration | `src/logbook/*`, `src/logbook_context.py`, `routes/logbook_routes.py` |
| Custom frontend DOM injection | `custom/frontend_assets.py` | `static/js/custom/index-ui.js` |
| Custom frontend app wiring | `custom/frontend_assets.py` | `static/js/custom/app-wiring.js` |
| Custom route title/favicon metadata | `custom/frontend_assets.py` | `static/js/custom/route-metadata.js` |
| Custom CSS | `custom/frontend_assets.py` | `static/css/billing.css`, `static/css/model-picker-custom.css`, `static/css/logbook.css` |
| Database schema | Keep minimal shared hooks | `core/database.py`, with custom query logic in `src/billing/*` or `src/logbook/*` |
| Tests | Test files own the behavior they protect | `tests/test_custom_*.py`, `tests/test_billing_*.py`, `tests/test_logbook_*.py` |

## How To Add Custom Backend Work

1. Put route registration in `custom/bootstrap.py`.
2. Keep route modules in `routes/` if they follow the app's normal FastAPI
   route pattern.
3. Put business logic in `src/<feature>/` instead of large route functions.
4. If database tables must live in `core/database.py`, keep that change small
   and put query behavior in a repository/service module.
5. Add focused tests for route behavior and data rules.

Shared app files should only need one narrow hook, such as:

```python
from custom.bootstrap import register_custom_features
register_custom_features(app, serve_index)
```

## How To Add Custom Frontend Work

1. Put browser JS under `static/js/custom/` when it is custom-only.
2. Put custom CSS under `static/css/` with feature-prefixed selectors.
3. Register new custom frontend files in `custom/frontend_assets.py`.
4. Keep `static/index.html` to placeholders such as:
   - `{{CUSTOM_HEAD_ASSETS}}`
   - `{{CUSTOM_STYLESHEETS}}`
   - `{{CUSTOM_BODY_MODULES}}`
5. Do not add custom route names, custom IDs, or custom asset paths directly to
   upstream-owned maps in `static/index.html` or `static/app.js`.
6. Add or update `tests/test_custom_index_ui.py` and
   `tests/test_custom_css_assets.py` when the asset boundary changes.

Browser files stay under `static/` because the browser imports them through
`/static/...` URLs. The ownership registry lives in `custom/`.

## Merge Discipline

Before adding a custom feature:

```powershell
git fetch upstream --prune
git rev-list --left-right --count upstream/main...HEAD
```

If upstream has new commits, merge upstream first unless there is a specific
reason to pause.

When resolving conflicts:

- upstream behavior wins by default;
- custom behavior stays only where intentional;
- if both need to exist, preserve upstream behavior and add custom behavior as
  a narrow overlay.

## Review Checklist

Before committing custom work, check:

- Is any shared file owning custom behavior directly?
- Can this be moved to `custom/bootstrap.py` or `custom/frontend_assets.py`?
- Are custom frontend assets registered from `custom/`?
- Are custom CSS selectors feature-prefixed?
- Are route handlers thin and business rules in `src/<feature>/`?
- Did focused Billing/Logbook/custom tests pass?
- Is the worktree free of private deployment data?

Suggested focused verification:

```powershell
py -3.12 -m pytest tests/test_custom_frontend_assets.py tests/test_custom_index_ui.py tests/test_custom_css_assets.py tests/test_custom_bootstrap.py tests/test_billing_routes.py tests/test_billing_usage.py tests/test_logbook_helpers.py tests/test_logbook_repository.py
node --check static/js/custom/route-metadata.js
node --check static/js/custom/index-ui.js
node --check static/js/custom/app-wiring.js
```
