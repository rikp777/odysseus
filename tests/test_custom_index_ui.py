from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_custom_index_ui_bootstrap_loads_before_app():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")

    custom_bootstrap = html.index('<script type="module" src="/static/js/custom/index-ui.js"></script>')
    custom_wiring = html.index('<script type="module" src="/static/js/custom/app-wiring.js"></script>')
    app = html.index('<script type="module" src="/static/app.js"></script>')

    assert custom_bootstrap < custom_wiring < app


def test_custom_index_ui_markup_stays_out_of_upstream_index():
    html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
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
