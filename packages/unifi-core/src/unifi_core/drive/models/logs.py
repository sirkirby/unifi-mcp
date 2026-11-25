"""System log entries from ``GET /proxy/drive/api/v2/systems/logs``.

A log entry carries an event name and the values to fill in, not a sentence.
The sentence comes from ``GET /proxy/drive/api/v2/systems/log-definitions``,
which maps each event name to a title and a description template such as
``"{drive} was inserted and is ready to use."``.
"""

from __future__ import annotations

import re
from typing import Annotated, Any, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, field_validator, model_validator

from unifi_core.drive.models._coerce import as_dict, number, text

LogSeverity = Literal["low", "medium", "high", "very_high"]
LogScope = Literal["all", "audit", "flow"]

MAX_LOG_LIMIT = 500
DEFAULT_LOG_LIMIT = 50

_PLACEHOLDER = re.compile(r"\{(\w+)\}")
_VERSION_SUFFIX = re.compile(r"^(\w+)V\d+$")


class DriveLogQuery(BaseModel):
    """Input: which system log entries to read, newest first."""

    model_config = ConfigDict(extra="forbid")

    limit: int = Field(
        default=DEFAULT_LOG_LIMIT, ge=1, le=MAX_LOG_LIMIT, description="Most entries to return in one page"
    )
    severities: list[LogSeverity] | None = Field(default=None, description="Only entries at these severities")
    category: str | None = Field(
        default=None, max_length=64, description="Only entries in this category, such as storage"
    )
    types: list[Annotated[str, Field(max_length=64)]] | None = Field(
        default=None, max_length=50, description="Only entries of these types, such as storagePool"
    )
    keyword: str | None = Field(default=None, max_length=200, description="Only entries matching this text")
    scope: LogScope | None = Field(
        default=None, description="all, audit (user and admin actions) or flow (file activity)"
    )
    after: AwareDatetime | None = Field(default=None, description="Only entries after this time")
    before: AwareDatetime | None = Field(default=None, description="Only entries before this time")
    cursor: str | None = Field(default=None, max_length=1024, description="next_cursor from the previous page")

    @field_validator("category", "keyword", "cursor", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: Any) -> Any:
        if isinstance(value, str):
            value = value.strip()
            return value or None
        return value

    @field_validator("severities", "types")
    @classmethod
    def _empty_is_unset(cls, value: list[str] | None) -> list[str] | None:
        if not value:
            return None
        return list(dict.fromkeys(value))

    @model_validator(mode="after")
    def _window(self) -> DriveLogQuery:
        if self.after and self.before and self.after >= self.before:
            raise ValueError("after must be earlier than before")
        return self


class DriveLogEntry(BaseModel):
    """One system log entry."""

    model_config = ConfigDict(extra="ignore")

    time: str | None = Field(default=None, description="When it was logged, ISO 8601 with the NAS's UTC offset")
    severity: str | None = Field(default=None, description="low, medium, high or very_high")
    category: str | None = Field(default=None, description="Log category, such as activity, storage or settings")
    type: str | None = Field(default=None, description="Log type within the category, such as storagePool")
    event: str | None = Field(default=None, description="Event name, such as DriveInserted")
    title: str | None = Field(default=None, description="Event title, such as Drive Inserted")
    message: str | None = Field(
        default=None, description="The entry as the Drive UI shows it; absent when Drive has no text for the event"
    )


class DriveLogPage(BaseModel):
    entries: list[DriveLogEntry]
    next_cursor: str | None = None


def _fill(value: Any) -> str | None:
    if isinstance(value, str):
        return value
    if number(value) is not None:
        return str(value)
    if isinstance(value, list) and value and all(isinstance(item, str) for item in value):
        return ", ".join(value)
    return None


def render_message(template: str | None, data: dict[str, Any]) -> str | None:
    """Fill ``{name}`` placeholders from ``data``; a placeholder with no usable value stays as it is."""
    if not template:
        return None

    def replace(match: re.Match[str]) -> str:
        filled = _fill(data.get(match.group(1)))
        return match.group(0) if filled is None else filled

    return _PLACEHOLDER.sub(replace, template)


def log_entry_from_api(raw: Any, definitions: dict[str, Any]) -> DriveLogEntry:
    """A log entry, with its title and message from the event definitions (``events`` of log-definitions).

    A legacy entry carries its own title and description, which win, as in the Drive UI.
    """
    entry = as_dict(raw)
    name = text(entry.get("name"))
    legacy = as_dict(entry.get("legacy"))
    definition = as_dict(definitions.get(name)) if name else {}
    title = text(legacy.get("title")) or text(definition.get("title"))
    template = text(legacy.get("description")) or text(definition.get("description"))
    event = None
    if name:
        match = _VERSION_SUFFIX.match(name)
        event = match.group(1) if match else name
    return DriveLogEntry(
        time=text(entry.get("createdAt")),
        severity=text(entry.get("severity")),
        category=text(entry.get("category")),
        type=text(entry.get("type")),
        event=event,
        title=title,
        message=render_message(template, as_dict(entry.get("data"))),
    )
