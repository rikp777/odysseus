from custom.frontend_assets import (
    CUSTOM_BODY_MODULES,
    CUSTOM_HEAD_SCRIPTS,
    CUSTOM_STYLESHEETS,
    inject_custom_frontend_assets,
    render_custom_body_modules,
    render_custom_head_assets,
    render_custom_stylesheets,
)


def test_custom_frontend_asset_renderers_use_registered_assets():
    head = render_custom_head_assets()
    styles = render_custom_stylesheets()
    body = render_custom_body_modules()

    for src in CUSTOM_HEAD_SCRIPTS:
        assert f'<script src="{src}"></script>' in head

    for href in CUSTOM_STYLESHEETS:
        assert f'<link rel="stylesheet" href="{href}">' in styles

    for src in CUSTOM_BODY_MODULES:
        assert f'<script type="module" src="{src}"></script>' in body


def test_inject_custom_frontend_assets_replaces_all_placeholders():
    html = "\n".join(
        [
            "{{CUSTOM_HEAD_ASSETS}}",
            "{{CUSTOM_STYLESHEETS}}",
            "{{CUSTOM_BODY_MODULES}}",
        ]
    )

    rendered = inject_custom_frontend_assets(html)

    assert "{{CUSTOM_HEAD_ASSETS}}" not in rendered
    assert "{{CUSTOM_STYLESHEETS}}" not in rendered
    assert "{{CUSTOM_BODY_MODULES}}" not in rendered
    assert "/static/js/custom/route-metadata.js" in rendered
    assert "/static/css/billing.css" in rendered
    assert "/static/js/custom/app-wiring.js" in rendered
