"""Shared validation helpers for Protect model/tool boundaries."""

from __future__ import annotations


def require_non_empty_actions(actions: object) -> None:
    """Reject action lists that would create UI-unopenable alarm rules."""
    if not isinstance(actions, list) or len(actions) == 0:
        raise ValueError(
            "actions must be a non-empty list. Protect accepts rules with no actions, "
            "but the resulting rule cannot be opened in the Protect UI."
        )
