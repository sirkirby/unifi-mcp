"""Shared MCP output schema helpers for UniFi tool responses."""

from __future__ import annotations

import inspect
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field


class UniFiToolResponse(BaseModel):
    """Structured view of the existing UniFi MCP tool response contract."""

    model_config = ConfigDict(extra="allow")

    success: bool | None = Field(
        default=None,
        description="True when the tool call succeeded; false for handled errors.",
    )
    data: Any | None = Field(default=None, description="Successful result payload.")
    error: str | None = Field(default=None, description="Actionable error message for handled failures.")
    requires_confirmation: bool | None = Field(
        default=None,
        description="True when a mutation preview requires caller confirmation.",
    )
    preview: Any | None = Field(default=None, description="Mutation preview payload returned before confirmation.")
    mutation_applied: bool | None = Field(
        default=None,
        description=(
            "For a confirmed write: true when it took effect, false when it did not, "
            "null when the outcome is unknown and the change may be live."
        ),
    )

    def model_dump(self, *args: Any, **kwargs: Any) -> dict[str, Any]:
        """Match the existing response shape by omitting absent optional fields.

        An explicit ``mutation_applied: None`` is kept: it means the write's
        outcome is unknown, which callers must not read as "not applied".
        """
        exclude_none = kwargs.setdefault("exclude_none", True)
        dumped = super().model_dump(*args, **kwargs)
        if exclude_none and self.mutation_applied is None and "mutation_applied" in self.model_fields_set:
            dumped["mutation_applied"] = None
        return dumped


def get_unifi_tool_response_output_schema() -> dict[str, Any]:
    """Return the MCP output schema for the standard UniFi tool response."""
    return UniFiToolResponse.model_json_schema()


def apply_unifi_tool_response_signature(func: Callable[..., Any]) -> Callable[..., Any]:
    """Annotate a wrapper so FastMCP can infer structured output metadata."""
    func.__signature__ = inspect.signature(func).replace(return_annotation=UniFiToolResponse)  # type: ignore[attr-defined]
    return func
