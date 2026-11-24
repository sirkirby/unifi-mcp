"""InnerSpace write acknowledgements: the core result, with ``success`` taken from the read-back."""

from __future__ import annotations

from typing import Any

from unifi_core.write_verification import WriteVerificationResult

from unifi_api.serializers._base import RenderKind, Serializer, SerializerContractError, register_serializer

WRITE_TOOLS = (
    "innerspace_create_walls",
    "innerspace_update_walls",
    "innerspace_remove_walls",
    "innerspace_create_wall_type",
    "innerspace_update_wall_type",
    "innerspace_create_attenuation_objects",
    "innerspace_update_attenuation_objects",
    "innerspace_remove_attenuation_objects",
    "innerspace_create_attenuation_object_type",
    "innerspace_update_attenuation_object_type",
    "innerspace_rename_floor_plan",
    "innerspace_set_floor_attenuation",
    "innerspace_reorder_floor_plans",
    "innerspace_set_plan_scale",
    "innerspace_set_project_unit",
)


@register_serializer(tools={name: {"kind": RenderKind.DETAIL} for name in WRITE_TOOLS})
class InnerSpaceWriteSerializer(Serializer):
    """Pass the core result through: ``success``, ``mutation_applied`` and the metadata.

    The metadata (``created_ids``, ``effects``, ``warnings``, ``missing`` and
    ``noop``) is flattened into the envelope, as on the MCP server. ``noop`` says
    why a call sent nothing: ``already_applied`` (an identical earlier create is in
    place) or ``none_found`` (none of the ids a remove names is in the project).
    An unknown outcome (``mutation_applied`` None) is never a success.
    """

    @staticmethod
    def serialize(obj: Any) -> dict:
        raise SerializerContractError("InnerSpace writes return a WriteVerificationResult")

    def serialize_action(self, result: Any, *, tool_name: str, redact_sensitive: bool = True) -> dict:
        if not isinstance(result, WriteVerificationResult):
            raise SerializerContractError(f"tool '{tool_name}' returned {type(result).__name__}, not a write result")
        payload = result.to_dict()
        if result.mutation_applied is None:
            payload["success"] = False
        return self._redact(payload, redact_sensitive=redact_sensitive)
