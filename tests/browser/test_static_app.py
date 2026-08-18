import pytest

pytestmark = pytest.mark.browser


def test_the_shell_paints_the_palette_surface(page, static_app):
    """The page background must come from shared/palette.json, not a CSS default.

    A page that renders with the browser's default white looks fine in light
    mode and wrong in dark mode, and nothing else in this suite would notice.
    """
    page.goto(static_app)
    background = page.evaluate("() => getComputedStyle(document.body).backgroundColor")
    assert background == "rgb(252, 252, 251)", background  # palette surface.light
