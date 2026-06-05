"""Custom frontend asset registry.

Static files stay under ``static/`` so the browser can load them, but the list of
custom assets is owned here to keep ``static/index.html`` close to upstream.
"""

from __future__ import annotations


CUSTOM_HEAD_SCRIPTS = (
    "/static/js/custom/route-metadata.js",
)

CUSTOM_STYLESHEETS = (
    "/static/css/billing.css",
    "/static/css/model-picker-custom.css",
    "/static/css/logbook.css",
)

CUSTOM_BODY_MODULES = (
    "/static/js/custom/index-ui.js",
    "/static/js/custom/app-wiring.js",
)


def render_custom_head_assets() -> str:
    return "\n".join(f'  <script src="{src}"></script>' for src in CUSTOM_HEAD_SCRIPTS)


def render_custom_stylesheets() -> str:
    return "\n".join(f'  <link rel="stylesheet" href="{href}">' for href in CUSTOM_STYLESHEETS)


def render_custom_body_modules() -> str:
    return "\n".join(f'<script type="module" src="{src}"></script>' for src in CUSTOM_BODY_MODULES)


def inject_custom_frontend_assets(html: str) -> str:
    """Replace custom asset placeholders in the static HTML shell."""
    replacements = {
        "{{CUSTOM_HEAD_ASSETS}}": render_custom_head_assets(),
        "{{CUSTOM_STYLESHEETS}}": render_custom_stylesheets(),
        "{{CUSTOM_BODY_MODULES}}": render_custom_body_modules(),
    }
    for placeholder, rendered in replacements.items():
        html = html.replace(placeholder, rendered)
    return html
