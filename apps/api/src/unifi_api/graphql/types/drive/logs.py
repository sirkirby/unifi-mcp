"""The UniFi Drive NAS's system log, newest first, one page at a time."""

from __future__ import annotations

import strawberry

from unifi_api.graphql.types.drive._base import DESCRIPTION, Projection


@strawberry.type(description=DESCRIPTION)
class DriveLogEntry(Projection):
    time: str | None = strawberry.field(description="When it was logged, ISO 8601 with the NAS's UTC offset")
    severity: str | None = strawberry.field(description="low, medium, high or very_high")
    category: str | None = strawberry.field(description="Log category, such as activity, storage or settings")
    type: str | None = strawberry.field(description="Log type within the category, such as storagePool")
    event: str | None = strawberry.field(description="Event name, such as DriveInserted")
    title: str | None = strawberry.field(description="Event title, such as Drive Inserted")
    message: str | None = strawberry.field(
        description="The entry as the Drive UI shows it; absent when Drive has no text for the event"
    )

    _columns = ["time", "severity", "category", "title", "message"]


@strawberry.type(description=DESCRIPTION)
class DriveLogPage(Projection):
    entries: list[DriveLogEntry] = strawberry.field(description="Log entries, newest first")
    next_cursor: str | None = strawberry.field(
        description="Pass it back as cursor, with the same filters, for the next page; absent on the last page"
    )

    _nested = {"entries": (DriveLogEntry, True)}
    _columns = ["next_cursor"]
