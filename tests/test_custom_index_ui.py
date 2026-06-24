from pathlib import Path

from custom.frontend_assets import (
    CUSTOM_BODY_MODULES,
    CUSTOM_HEAD_SCRIPTS,
    inject_custom_frontend_assets,
)


ROOT = Path(__file__).resolve().parents[1]


def _index_html(render_custom_assets: bool = False) -> str:
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    if render_custom_assets:
        return inject_custom_frontend_assets(html)
    return html


def test_custom_index_ui_bootstrap_loads_before_app():
    html = _index_html(render_custom_assets=True)

    route_metadata = html.index('<script src="/static/js/custom/route-metadata.js"></script>')
    route_metadata_hook = html.index("window.__odysseusCustomRouteMetadata")
    custom_bootstrap = html.index('<script type="module" src="/static/js/custom/index-ui.js"></script>')
    custom_wiring = html.index('<script type="module" src="/static/js/custom/app-wiring.js"></script>')
    app = html.index('<script type="module" src="/static/app.js"></script>')

    assert route_metadata < route_metadata_hook
    assert custom_bootstrap < custom_wiring < app


def test_custom_index_ui_markup_stays_out_of_upstream_index():
    html = _index_html()
    custom_ui = (ROOT / "static" / "js" / "custom" / "index-ui.js").read_text(encoding="utf-8")

    custom_markers = [
        'id="rail-logbook"',
        'id="rail-logbook-atlas"',
        'id="billing-spend-pill"',
        'id="tool-logbook-btn"',
        'id="tool-logbook-atlas-btn"',
        'data-ui-key="tool-logbook"',
        'data-ui-key="tool-logbook-atlas"',
        'DigitalOcean Inference',
        'id="cloud-billing-card"',
    ]

    for marker in custom_markers:
        assert marker not in html
        assert marker in custom_ui

    assert "installCustomIndexUi" in custom_ui


def test_custom_app_wiring_stays_out_of_upstream_app_entrypoint():
    app = (ROOT / "static" / "app.js").read_text(encoding="utf-8")
    custom_wiring = (ROOT / "static" / "js" / "custom" / "app-wiring.js").read_text(encoding="utf-8")

    custom_markers = [
        "logbookModule",
        "logbookAtlasModule",
        "initBillingSpend",
        "tool-logbook",
        "rail-logbook",
        "/logbook",
    ]

    for marker in custom_markers:
        assert marker not in app
        assert marker in custom_wiring

    assert "installCustomAppWiring" in custom_wiring


def test_custom_route_metadata_stays_out_of_upstream_index():
    html = _index_html()
    metadata = (ROOT / "static" / "js" / "custom" / "route-metadata.js").read_text(encoding="utf-8")

    custom_markers = [
        "'/logbook'",
        "'/logbook/atlas'",
        "Logbook - Odysseus",
        "People & Places - Odysseus",
    ]

    for marker in custom_markers:
        assert marker not in html
        assert marker in metadata

    assert "__odysseusCustomRouteMetadata" in html
    assert "__odysseusCustomRouteMetadata" in metadata


def test_sidenav_has_workspace_and_ai_sections_not_tools_section():
    html = _index_html()
    assert 'id="workspace-section"' in html
    assert 'id="ai-section"' in html
    assert 'id="logbook-section"' in html
    assert 'id="tools-section"' not in html


def test_sidenav_logbook_section_starts_hidden():
    html = _index_html()
    idx = html.index('id="logbook-section"')
    # The opening div tag containing logbook-section must carry display:none
    tag_start = html.rindex('<', 0, idx)
    tag_end = html.index('>', idx)
    tag = html[tag_start:tag_end + 1]
    assert 'display:none' in tag


def test_theme_button_in_user_bar_not_in_workspace_section():
    html = _index_html()
    theme_idx = html.index('id="tool-theme-btn"')
    # user-bar comes after workspace-section/ai-section in DOM
    ai_section_end = html.index('</div>', html.index('id="ai-section"'))
    user_bar_idx = html.index('id="sidebar-user-bar"')
    assert theme_idx > user_bar_idx or theme_idx > ai_section_end
    # Must NOT appear inside workspace-section
    ws_start = html.index('id="workspace-section"')
    ws_end = html.index('id="ai-section"')
    assert theme_idx < ws_start or theme_idx > ws_end


def test_cookbook_btn_in_ai_section():
    html = _index_html()
    ai_start = html.index('id="ai-section"')
    logbook_start = html.index('id="logbook-section"')
    cookbook_idx = html.index('id="tool-cookbook-btn"')
    assert ai_start < cookbook_idx < logbook_start


def test_billing_pill_hidden_class_has_css_rule():
    css = (ROOT / "static" / "css" / "billing.css").read_text(encoding="utf-8")
    assert ".billing-spend-pill.hidden" in css
    # Rule must contain display:none
    idx = css.index(".billing-spend-pill.hidden")
    block_end = css.index("}", idx)
    block = css[idx:block_end]
    assert "display" in block and "none" in block


def test_app_wiring_has_cookbook_auto_hide():
    wiring = (ROOT / "static" / "js" / "custom" / "app-wiring.js").read_text(encoding="utf-8")
    assert "syncCookbookVisibility" in wiring
    assert "_hasLocalEndpoint" in wiring
    assert "odysseus-integrations-changed" in wiring
    assert "rail-cookbook" in wiring


def test_index_ui_injects_logbook_into_section_not_after_calendar():
    ui = (ROOT / "static" / "js" / "custom" / "index-ui.js").read_text(encoding="utf-8")
    # Must target logbook-section
    assert "logbook-section" in ui
    # Must NOT use calendar-btn as insertion anchor
    assert "tool-calendar-btn" not in ui


def test_custom_frontend_assets_are_registered_from_custom_folder():
    html = _index_html()
    rendered = _index_html(render_custom_assets=True)

    assert "{{CUSTOM_HEAD_ASSETS}}" in html
    assert "{{CUSTOM_STYLESHEETS}}" in html
    assert "{{CUSTOM_BODY_MODULES}}" in html

    for src in CUSTOM_HEAD_SCRIPTS:
        assert src not in html
        assert src in rendered

    for src in CUSTOM_BODY_MODULES:
        assert src not in html
        assert src in rendered
