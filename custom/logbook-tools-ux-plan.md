# Logbook Tools UX Plan

## Problem

The previous Tools area made the Write screen feel heavy and poorly organized. It opened as a full-width block above the editor, creating a large empty band and mixing unrelated controls in one place.

The Logbook writing flow should stay light:

- Open Logbook.
- Write messy notes.
- Mark important text only when needed.
- Save or Enhance after writing.

## UX Direction

Keep the Write tab focused on writing. Advanced controls should be available, but they should not dominate the writing surface.

## Final Layout

### Write Header

Visible actions:

- Days
- Enhance
- More

### Main Editor Toolbar

Always visible, compact, and directly tied to selected text:

- Bold
- Italic
- Strikethrough
- Link
- Person
- Place
- Meal
- Remove link

Food tracking remains available through the Meal action. Selecting text and clicking Meal stores it as `data:food`.

### More Popover

The old full-width Tools block is replaced by a compact popover with three groups.

#### Format

- H1
- H2
- H3
- Quote
- Bullet list
- Numbered list
- Inline code
- Code block
- Horizontal rule

#### Editor

- Editor
- Markdown

`Raw` is renamed to `Markdown`. When Markdown is active, the UI shows a small state badge instead of adding more toolbar clutter.

#### Entry

- History

## History

History opens as a right-side drawer overlay. It no longer pushes the editor down or consumes vertical space while writing.

The drawer contains:

- Revision list
- Preview actions
- Restore action
- Refresh
- Close

## Implementation Notes

Changed files:

- `static/js/logbook.js`
- `static/css/logbook.css`
- `tests/test_logbook_tab_layout_css.py`

Key implementation points:

- Removed the old `logbook-write-tools` layout.
- Added `logbook-write-more-menu` as a compact popover.
- Added `logbook-history-drawer` as a non-blocking overlay.
- Updated tests so the old crowded Tools layout cannot return unnoticed.

## Verification

Automated checks passed:

- `node --check static/js/logbook.js`
- `venv/bin/python -m pytest tests/test_logbook_tab_layout_css.py tests/test_logbook_editor_js.py tests/test_logbook_entities_js.py tests/test_logbook_helpers.py -q`
- `git diff --check`

Browser verification covered:

- Default Write screen
- More popover
- Markdown mode
- History drawer
- History close flow

Screenshots:

- `output/playwright/logbook-more-popover.png`
- `output/playwright/logbook-markdown-mode.png`
- `output/playwright/logbook-history-drawer.png`

