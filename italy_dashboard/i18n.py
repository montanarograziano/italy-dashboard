"""Reactive translation helper over the plain-data dictionaries."""

from __future__ import annotations

import reflex as rx

from italy_dashboard.state import AppState
from italy_dashboard.translations import EN, IT


def t(key: str) -> rx.Var:
    """Reactive translated string for a UI key."""
    return rx.cond(AppState.lang == "it", IT[key], EN[key])
