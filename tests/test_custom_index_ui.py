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
