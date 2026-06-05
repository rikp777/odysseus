# Custom Fork Upstream Maintenance Plan

Last reviewed: 2026-06-05

## Principle

`upstream/main` is the source of truth. The `custom` branch should behave like a
small overlay for personal features, mainly billing, model cost visibility, and
Daily Logbook. Custom work is allowed, but it should not quietly replace,
weaken, or fork upstream behavior unless that is an explicit personal-product
decision documented here.

## Current Health Snapshot

The fork is mostly healthy, but there are real maintenance risks.

- `custom` is ahead of `upstream/main` by custom work, but it is currently
  missing one upstream commit.
- Missing upstream commit: `e0e250d`, `Calendar: cross-session delete sync - 404
  = success, refetch on tab focus`, committed on 2026-06-05.
- The missing commit affects `static/js/calendar.js` and should be integrated
  while preserving the custom `mapSearchUrl` helper.
- The focused custom test set passed: `291 passed`.
- Full test comparison in the same Windows/Python UTF-8 environment:
  - custom: `2240 passed`, `61 failed`, `3 skipped`
  - upstream: `2125 passed`, `62 failed`, `3 skipped`
- The red tests are mostly inherited environment fragility around Windows paths,
  Bash, Node ESM imports, and temp path assumptions. They are not currently a
  sign that billing or logbook degraded upstream.

## Main Risk Areas

Custom code is reasonably modular in billing and logbook, but the branch touches
too much shared surface to treat merges casually.

High-risk shared files:

- `core/database.py`
- `src/llm_core.py`
- `src/tool_execution.py`
- `src/tool_implementations.py`
- `src/tool_index.py`
- shared route files under `routes/`
- `static/style.css`
- broad frontend modules such as `static/app.js`, `static/index.html`, and
  shared `static/js/*` helpers

Lower-risk custom-owned areas:

- `routes/billing_routes.py`
- `src/billing/*`
- `src/billing_usage.py`
- `routes/logbook_routes.py`
- `src/logbook/*`
- `src/logbook_context.py`
- `static/js/billing/*`
- `static/js/logbook*`
- `docs/daily-logbook.md`
- `custom/*`

## Immediate Plan

1. Get the branch fully caught up with upstream.

   - Run `git fetch upstream --prune`.
   - Merge `upstream/main` into `custom`, or cherry-pick `e0e250d` if that is
     the only missing upstream commit.
   - In `static/js/calendar.js`, preserve the custom `mapSearchUrl` integration
     and also apply upstream's delete/refetch behavior:
     - treat calendar delete `404` as success;
     - clear/refetch calendar ranges on tab visibility/focus.

2. Commit the current model-capability cleanup separately.

   The current uncommitted work centralizes chat-capable model filtering in
   `src/model_capabilities.py`. This is good directionally because it removes
   duplicated route-local heuristics. Keep it as its own commit so it can be
   reviewed and reverted independently if needed.

   Verify with:

   ```powershell
   py -3.12 -m pytest tests/test_model_routes.py tests/test_endpoint_resolver.py tests/test_provider_endpoints.py tests/test_session_model_capabilities.py
   ```

3. Run targeted custom verification after the upstream catch-up.

   ```powershell
   py -3.12 -m pytest tests/test_billing_events.py tests/test_billing_routes.py tests/test_billing_usage.py tests/test_llm_usage_accounting.py tests/test_logbook_helpers.py tests/test_logbook_repository.py tests/test_model_pricing.py tests/test_model_routes.py tests/test_endpoint_resolver.py tests/test_provider_endpoints.py tests/test_session_model_capabilities.py
   ```

4. Run a full-suite comparison when behavior looks risky.

   On Windows, use UTF-8 mode so collection and frontend-helper tests are closer
   to the upstream comparison baseline:

   ```powershell
   $env:PYTHONUTF8='1'; py -3.12 -m pytest
   ```

   The full suite does not need to be perfectly green locally before every
   custom commit, because upstream itself has inherited Windows/Node/Bash
   failures in this environment. What matters is whether the fork introduces new
   failures outside the known baseline.

5. Push `custom` after clean logical commits.

   The branch was observed as `custom...origin/custom [ahead 103]`. That is too
   much unpushed work for a personal production branch. Push after the upstream
   catch-up and after committing the model-capability cleanup.

## Ongoing Merge Discipline

Use this loop regularly:

1. Fetch upstream.

   ```powershell
   git fetch upstream --prune
   git rev-list --left-right --count upstream/main...HEAD
   git log --oneline --left-right upstream/main...HEAD
   ```

2. Merge upstream before building more custom features.

   ```powershell
   git merge upstream/main
   ```

3. Resolve conflicts with this rule:

   - upstream behavior wins by default;
   - custom billing/logbook behavior stays only where it is intentional;
   - if both need to exist, preserve upstream behavior first and add the custom
     integration as a narrow layer.

4. Check diff shape before committing.

   ```powershell
   git diff --stat upstream/main...HEAD
   git diff --name-status upstream/main...HEAD
   ```

   If a custom feature touches many shared files, stop and ask whether the code
   can be moved behind a route, service, adapter, or frontend module.

5. Run focused tests for changed areas.

   Examples:

   ```powershell
   py -3.12 -m pytest tests/test_billing_routes.py tests/test_billing_usage.py
   py -3.12 -m pytest tests/test_logbook_helpers.py tests/test_logbook_repository.py
   py -3.12 -m pytest tests/test_model_routes.py tests/test_endpoint_resolver.py
   ```

## Refactoring Targets To Reduce Future Drift

These are not blockers, but they will make future upstream merges safer.

1. Reduce `core/database.py` pressure.

   Keep custom tables there only as much as the current app architecture
   requires. Put custom query behavior in `src/billing/*` and `src/logbook/*`
   repositories/services instead of adding more broad database helpers.

2. Avoid more global CSS churn.

   Prefer feature-prefixed selectors for billing and logbook. Keep broad layout
   and theme changes small because `static/style.css` is a major merge-conflict
   magnet.

3. Keep model-cost behavior behind small helpers.

   Pricing and capability rules should stay in modules such as
   `src/model_pricing.py`, `src/provider_identity.py`, and
   `src/model_capabilities.py`, with routes calling those helpers instead of
   duplicating provider heuristics.

4. Keep billing provider logic adapter-based.

   Provider-specific code belongs under `src/billing/adapters/*`. Routes should
   orchestrate and validate; they should not know provider API details.

5. Keep Logbook AI optional.

   Manual Logbook writing and atlas management should keep working when no LLM
   endpoint is configured. AI behavior should be preview-first and owner-scoped.

## Definition Of Healthy

The custom fork is healthy when:

- `git rev-list --left-right --count upstream/main...HEAD` shows no upstream
  commits missing unless a skip is documented;
- billing/logbook focused tests pass;
- full-suite failures are not meaningfully worse than upstream in the same
  environment;
- custom commits are small enough to review by feature;
- upstream conflict resolutions preserve upstream behavior by default;
- private deployment details stay out of Git.

