"""Branded 404: the same header/nav shell every other page uses.

Registered via `app.add_page(not_found_page, route="404")`
(italy_dashboard.py) -- Reflex's supported hook for a custom not-found page
(reflex/app.py: `add_page`'s `route == constants.Page404.SLUG` branch, and
`compiler.py` auto-registers its own bare `span("404: Page not found")` at
that same route if the app never does). Without this, an unmatched path
(a stale bookmark, a typo, a dangling link) rendered plain unstyled text with
no header, no nav and no way back into the app except the browser's back
button.

`has_loaded=False`, not `EducationState.has_loaded` or similar: this page has
no state of its own to load, and passing a literal `False` means
`components.shell()`'s top banner slot renders `rx.fragment()` (nothing)
forever rather than ever evaluating `AppState.data_ready` -- the 404 page
should never show the "no data snapshot" callout, which is about a missing
mart, not a missing route.
"""

import reflex as rx

from italy_dashboard import theme
from italy_dashboard.components import shell
from italy_dashboard.i18n import t


def not_found_page() -> rx.Component:
    return shell(
        rx.heading(t("not_found_title"), size="6", color=theme.ink_primary()),
        rx.text(t("not_found_body"), color=theme.ink_secondary()),
        rx.link(
            t("not_found_cta"),
            href="/",
            color=theme.ink_primary(),
            font_weight="600",
        ),
        has_loaded=False,
    )
