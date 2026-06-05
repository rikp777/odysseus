from pathlib import Path

from custom.frontend_assets import CUSTOM_STYLESHEETS, inject_custom_frontend_assets


ROOT = Path(__file__).resolve().parents[1]


def test_custom_css_files_load_after_base_stylesheet():
    raw_html = (ROOT / "static" / "index.html").read_text(encoding="utf-8")
    html = inject_custom_frontend_assets(raw_html)

    base = html.index('/static/style.css')
    billing = html.index('/static/css/billing.css')
    model_picker = html.index('/static/css/model-picker-custom.css')
    logbook = html.index('/static/css/logbook.css')

    assert base < billing < model_picker < logbook
    assert CUSTOM_STYLESHEETS == (
        "/static/css/billing.css",
        "/static/css/model-picker-custom.css",
        "/static/css/logbook.css",
    )
    for href in CUSTOM_STYLESHEETS:
        assert href not in raw_html


def test_custom_css_blocks_stay_extracted_from_base_stylesheet():
    style = (ROOT / "static" / "style.css").read_text(encoding="utf-8")
    billing = (ROOT / "static" / "css" / "billing.css").read_text(encoding="utf-8")
    model_picker = (ROOT / "static" / "css" / "model-picker-custom.css").read_text(encoding="utf-8")
    logbook = (ROOT / "static" / "css" / "logbook.css").read_text(encoding="utf-8")

    assert "Custom billing styles moved to /static/css/billing.css" in style
    assert "Custom model picker pricing styles moved to /static/css/model-picker-custom.css" in style
    assert "Custom Daily Logbook styles moved to /static/css/logbook.css" in style

    assert ".cloud-billing-toggle" in billing
    assert ".model-picker-wrap" in model_picker
    assert ".logbook-modal" in logbook

    assert ".cloud-billing-toggle" not in style
    assert ".logbook-modal {" not in style
