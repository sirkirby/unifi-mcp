"""Helpers for validating Protect bootstrap/public API ID portability."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping


@dataclass(frozen=True)
class IdPortabilityReport:
    """Result of comparing IDs from two Protect API surfaces."""

    resource_type: str
    bootstrap_ids: tuple[str, ...]
    public_ids: tuple[str, ...]
    missing_from_public: tuple[str, ...]
    missing_from_bootstrap: tuple[str, ...]

    @property
    def portable(self) -> bool:
        """Return true when the two API surfaces expose the same ID set."""
        return not self.missing_from_public and not self.missing_from_bootstrap

    def raise_for_mismatch(self) -> None:
        """Raise a clear error if the two API surfaces do not share IDs."""
        if self.portable:
            return
        details: list[str] = []
        if self.missing_from_public:
            details.append(f"missing from public API: {list(self.missing_from_public)}")
        if self.missing_from_bootstrap:
            details.append(f"missing from bootstrap data: {list(self.missing_from_bootstrap)}")
        raise ValueError(
            f"Protect public Integration API IDs for {self.resource_type} are not portable with bootstrap IDs "
            f"({'; '.join(details)}). Do not use existing list-tool IDs for public API-backed "
            "capabilities until this mapping is resolved."
        )


def _item_id(item: Any) -> str | None:
    if isinstance(item, str):
        return item
    if isinstance(item, Mapping):
        value = item.get("id")
    else:
        value = getattr(item, "id", None)
    if value in (None, ""):
        return None
    return str(value)


def _ids_from_items(items: Mapping[str, Any] | Iterable[Any] | None) -> frozenset[str]:
    if items is None:
        return frozenset()
    if isinstance(items, Mapping):
        return frozenset(str(key) for key in items.keys() if key not in (None, ""))
    return frozenset(item_id for item in items if (item_id := _item_id(item)) is not None)


def compare_id_portability(
    *,
    resource_type: str,
    bootstrap_items: Mapping[str, Any] | Iterable[Any] | None,
    public_items: Mapping[str, Any] | Iterable[Any] | None,
    raise_on_mismatch: bool = False,
) -> IdPortabilityReport:
    """Compare Protect bootstrap/private IDs with public Integration API IDs."""
    bootstrap_ids = _ids_from_items(bootstrap_items)
    public_ids = _ids_from_items(public_items)
    report = IdPortabilityReport(
        resource_type=resource_type,
        bootstrap_ids=tuple(sorted(bootstrap_ids)),
        public_ids=tuple(sorted(public_ids)),
        missing_from_public=tuple(sorted(bootstrap_ids - public_ids)),
        missing_from_bootstrap=tuple(sorted(public_ids - bootstrap_ids)),
    )
    if raise_on_mismatch:
        report.raise_for_mismatch()
    return report
