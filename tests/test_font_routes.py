import asyncio
from pathlib import Path

from routes.font_routes import _derive_family, setup_font_routes


ROOT = Path(__file__).resolve().parents[1]


def test_derive_family_keeps_jetbrains_together():
    assert _derive_family("JetBrainsMono-Regular.woff2") == "JetBrains Mono"


def test_derive_family_splits_common_family_suffixes():
    assert _derive_family("FiraCode-SemiBold.ttf") == "Fira Code"
    assert _derive_family("NotoSans-Bold.otf") == "Noto Sans"
    assert _derive_family("RobotoSlab-Bold.woff2") == "Roboto Slab"


def test_jetbrains_mono_is_vendored_as_custom_font_asset():
    font_path = ROOT / "static" / "fonts" / "custom" / "JetBrainsMono-Regular.woff2"
    license_path = ROOT / "licenses" / "JetBrainsMono-OFL-LICENSE.txt"

    assert font_path.is_file()
    assert font_path.stat().st_size > 0
    assert license_path.is_file()
    assert "SIL OPEN FONT LICENSE" in license_path.read_text(encoding="utf-8")


def test_custom_fonts_route_exposes_vendored_jetbrains_mono():
    router = setup_font_routes()
    route = next(route for route in router.routes if getattr(route, "path", "") == "/api/fonts/custom")

    fonts = asyncio.run(route.endpoint())["fonts"]
    assert "JetBrains Mono" in fonts
    assert {
        "file": "JetBrainsMono-Regular.woff2",
        "url": "/static/fonts/custom/JetBrainsMono-Regular.woff2",
        "format": "woff2",
    } in fonts["JetBrains Mono"]
