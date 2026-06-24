import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LOGBOOK_CSS = (ROOT / "static" / "css" / "logbook.css").read_text(encoding="utf-8")
LOGBOOK_JS = (ROOT / "static" / "js" / "logbook.js").read_text(encoding="utf-8")
LOGBOOK_TABS_JS = (ROOT / "static" / "js" / "logbook" / "tabs.js").read_text(encoding="utf-8")


def _rule(selector: str) -> str:
    start = LOGBOOK_CSS.index(selector)
    open_brace = LOGBOOK_CSS.index("{", start)
    close_brace = LOGBOOK_CSS.index("}", open_brace)
    return LOGBOOK_CSS[start:close_brace]


def test_logbook_tabs_have_rendered_content_surfaces():
    tabs_match = re.search(r"LOGBOOK_TABS = Object\.freeze\(\[([^\]]+)\]\)", LOGBOOK_TABS_JS)
    assert tabs_match is not None

    tabs = re.findall(r"'([^']+)'", tabs_match.group(1))
    sections = set(re.findall(r'data-mobile-section="([^"]+)"', LOGBOOK_JS))

    assert tabs == ["write", "mood", "data", "review", "people", "places", "ai"]
    assert set(tabs) <= sections
    assert 'role="tablist" aria-label="Logbook sections"' in LOGBOOK_JS
    assert 'role="tab" class="logbook-tab" data-logbook-tab="${tab}"' in LOGBOOK_JS


def test_logbook_write_screen_keeps_browse_and_more_opt_in():
    assert 'id="logbook-toggle-browse"' in LOGBOOK_JS
    assert 'id="logbook-toggle-write-more"' in LOGBOOK_JS
    assert 'id="logbook-write-more-menu"' in LOGBOOK_JS
    assert 'id="logbook-write-tools"' not in LOGBOOK_JS
    assert 'logbook-write-tools' not in LOGBOOK_CSS
    assert 'class="logbook-link-toolbar logbook-inline-format-toolbar"' in LOGBOOK_JS
    assert "${_compactFormatToolbarHtml()}" in LOGBOOK_JS
    assert "More</button>" in LOGBOOK_JS

    assert "display: none;" in _rule('.logbook-body[data-active-tab="write"] .logbook-nav')
    assert "grid-template-columns: minmax(210px, 250px) minmax(430px, 1fr);" in _rule(
        '.logbook-body[data-active-tab="write"].browse-open'
    )
    assert "display: block;" in _rule('.logbook-body[data-active-tab="write"].browse-open .logbook-nav')


def test_logbook_more_menu_and_history_do_not_crowd_editor():
    assert "function _writeMoreMenuHtml" in LOGBOOK_JS
    assert "_advancedFormatToolbarHtml('logbook-more-toolbar')" in LOGBOOK_JS
    assert "Markdown</button>" in LOGBOOK_JS
    assert "Raw</button>" not in LOGBOOK_JS
    assert 'class="logbook-history-drawer"' in LOGBOOK_JS
    assert "_historyHtml({ includeClose: true })" in LOGBOOK_JS

    more_rule = _rule(".logbook-write-more-menu {")
    drawer_rule = _rule(".logbook-history-drawer {")

    assert "position: absolute;" in more_rule
    assert "position: absolute;" in drawer_rule
    assert "box-shadow:" in more_rule
    assert "box-shadow:" in drawer_rule


def test_logbook_enhance_actions_use_dense_desktop_layout():
    actions_rule = _rule(".logbook-ai-actions {")
    meter_rule = _rule(".logbook-ai-meter-grid {")
    mobile_actions_rule = _rule("  .logbook-ai-actions,")

    assert "grid-template-columns: repeat(3, minmax(0, 1fr));" in actions_rule
    assert "grid-template-columns: repeat(4, minmax(0, 1fr));" in meter_rule
    assert "grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile_actions_rule


def test_logbook_common_formatting_stays_visible_with_editor():
    assert "function _compactFormatToolbarHtml()" in LOGBOOK_JS
    assert "_formatButtonHtml('bold', 'Bold', 'bold')" in LOGBOOK_JS
    assert "_formatButtonHtml('link', 'Link', 'link')" in LOGBOOK_JS
    assert "_linkSelectionButtonHtml('person', 'Link selected text as person', 'person')" in LOGBOOK_JS
    assert "_linkSelectionButtonHtml('location', 'Link selected text as place', 'location')" in LOGBOOK_JS
    assert "_dataSelectionButtonHtml('food', 'Track selected text as meal', 'food')" in LOGBOOK_JS
    assert "data-logbook-data-selection" in LOGBOOK_JS
    assert "Link selected text as food" not in LOGBOOK_JS
    assert "linkKind: 'food'" not in LOGBOOK_JS

    toolbar_rule = _rule(".logbook-inline-format-toolbar {")
    write_section_rule = _rule(".logbook-write-section {")
    rich_rule = _rule(".logbook-rich-content {")

    assert "align-self: flex-start;" in toolbar_rule
    assert "flex-direction: column;" in write_section_rule
    assert "flex: 1 1 auto;" in rich_rule


def test_logbook_mobile_tabs_scroll_instead_of_clipping():
    tabs_rule = _rule(".logbook-mobile-tabs {")
    mobile_tabs_rule = _rule("  .logbook-mobile-tabs {")
    mobile_tab_rule = _rule("  .logbook-tab {")

    assert "overflow-x: auto;" in tabs_rule
    assert "overflow-x: auto;" in mobile_tabs_rule
    assert "flex-wrap: nowrap;" in mobile_tabs_rule
    assert "flex: 0 0 auto;" in mobile_tab_rule


def test_desktop_write_mood_and_data_tabs_hide_sibling_editor_sections():
    hidden_siblings = [
        '.logbook-body[data-active-tab="write"] .logbook-editor [data-mobile-section="mood"]',
        '.logbook-body[data-active-tab="write"] .logbook-editor [data-mobile-section="data"]',
        '.logbook-body[data-active-tab="mood"] .logbook-editor [data-mobile-section="write"]',
        '.logbook-body[data-active-tab="mood"] .logbook-editor [data-mobile-section="data"]',
        '.logbook-body[data-active-tab="data"] .logbook-editor [data-mobile-section="write"]',
        '.logbook-body[data-active-tab="data"] .logbook-editor [data-mobile-section="mood"]',
    ]

    for selector in hidden_siblings:
        assert "display: none;" in _rule(selector)


def test_desktop_mood_and_data_tabs_hide_write_only_editor_chrome():
    write_only_chrome = [
        '.logbook-body[data-active-tab="mood"] .logbook-editor-head',
        '.logbook-body[data-active-tab="mood"] #logbook-history-panel',
        '.logbook-body[data-active-tab="mood"] .logbook-link-toolbar',
        '.logbook-body[data-active-tab="data"] .logbook-editor-head',
        '.logbook-body[data-active-tab="data"] #logbook-history-panel',
        '.logbook-body[data-active-tab="data"] .logbook-link-toolbar',
    ]

    for selector in write_only_chrome:
        assert "display: none;" in _rule(selector)


def test_desktop_review_people_places_and_enhance_tabs_are_isolated_panels():
    hidden_containers = [
        '.logbook-body[data-active-tab="review"] .logbook-nav',
        '.logbook-body[data-active-tab="review"] .logbook-editor',
        '.logbook-body[data-active-tab="review"] .logbook-side',
        '.logbook-body[data-active-tab="people"] .logbook-nav',
        '.logbook-body[data-active-tab="people"] .logbook-editor',
        '.logbook-body[data-active-tab="people"] .logbook-review-panel',
        '.logbook-body[data-active-tab="places"] .logbook-nav',
        '.logbook-body[data-active-tab="places"] .logbook-editor',
        '.logbook-body[data-active-tab="places"] .logbook-review-panel',
        '.logbook-body[data-active-tab="ai"] .logbook-nav',
        '.logbook-body[data-active-tab="ai"] .logbook-editor',
        '.logbook-body[data-active-tab="ai"] .logbook-review-panel',
    ]

    for selector in hidden_containers:
        assert "display: none;" in _rule(selector)

    assert "display: grid;" in _rule('.logbook-body[data-active-tab="review"] .logbook-review-panel')
    for tab in ["people", "places", "ai"]:
        assert "display: block;" in _rule(f'.logbook-body[data-active-tab="{tab}"] .logbook-side')
        assert "display: block;" in _rule(
            f'.logbook-body[data-active-tab="{tab}"] .logbook-side > [data-mobile-section="{tab}"]'
        )
