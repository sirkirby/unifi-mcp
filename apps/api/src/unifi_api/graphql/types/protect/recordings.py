"""Strawberry types for protect/recordings (Phase 6 PR3 Task B).

Two read serializers move here from
``unifi_api.serializers.protect.recordings``:

- ``Recording`` — protect_list_recordings (LIST, resource-registered as
  both ``protect/recordings`` and ``protect/recordings/{id}`` since the
  REST detail endpoint filters the same list response by id rather than
  hitting a dedicated ``protect_get_recording`` tool — UniFi Protect
  exposes a single per-camera recording window, not discrete segments).
  The manager helper renames ``camera_id`` -> ``camera`` per the prior
  serializer contract.
- ``RecordingStatusList`` — protect_get_recording_status (DETAIL
  wrapper-dict pass-through). Manager returns
  ``{cameras: [...], count}``; we mirror that exactly. Per-camera rows
  are heterogeneous (recording_mode, video_stats sub-map, etc.), so we
  keep them as a JSON sub-map rather than a typed sub-row class.

Mutation acks (``protect_delete_recording`` / ``protect_export_clip``)
stay in the serializer module — those tools dispatch via the manager's
preview-and-confirm path.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Annotated, Any

import strawberry
from strawberry.types import Info

if TYPE_CHECKING:
    from unifi_api.graphql.types.protect.cameras import Camera


def _get(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw.get(key, default)
    return getattr(obj, key, default)


@strawberry.type(description="A UniFi Protect recording window for a camera.")
class Recording:
    """Mirrors ``RecordingSerializer.serialize`` projection.

    UniFi Protect exposes a continuous time window per camera rather
    than discrete recording segments; the manager helper returns a
    single dict describing that window, and the REST detail endpoint
    filters this same list shape by ``id``. We rename ``camera_id`` ->
    ``camera`` to match the prior dict contract.
    """

    id: strawberry.ID | None
    type: str | None
    camera: strawberry.ID | None
    start: str | None
    end: str | None
    file_size: int | None

    # Context for relationship edges — NOT in SDL, NOT in to_dict().
    _controller_id: strawberry.Private[str | None] = None
    _camera_id: strawberry.Private[str | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {
            "kind": kind,
            "primary_key": "id",
            "display_columns": ["type", "start", "end", "file_size"],
            "sort_default": "start:desc",
        }

    @classmethod
    def from_manager_output(cls, obj: Any) -> "Recording":
        cam_id = _get(obj, "camera_id")
        inst = cls(
            id=_get(obj, "id"),
            type=_get(obj, "type"),
            camera=cam_id,
            start=_get(obj, "start"),
            end=_get(obj, "end"),
            file_size=_get(obj, "file_size"),
        )
        # Seed the private linkage from the same source so `cameraDetail`
        # works even when no resolver explicitly sets it (e.g. in REST).
        inst._camera_id = cam_id
        return inst

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "type": self.type,
            "camera": self.camera,
            "start": self.start,
            "end": self.end,
            "file_size": self.file_size,
        }

    @strawberry.field(description="The camera this recording came from.")
    async def camera_detail(
        self,
        info: Info,
    ) -> Annotated["Camera", strawberry.lazy("unifi_api.graphql.types.protect.cameras")] | None:
        """Resolves the parent camera for this recording.

        Named ``cameraDetail`` (not ``camera``) to avoid colliding with the
        public scalar ``camera: ID`` field that REST consumers depend on.
        """
        from unifi_api.graphql.resolvers.protect import _fetch_cameras
        from unifi_api.graphql.types.protect.cameras import Camera

        if not self._controller_id or not self._camera_id:
            return None
        all_cameras = await _fetch_cameras(info.context, self._controller_id)
        for c in all_cameras:
            cam_id = _get(c, "id")
            if cam_id == self._camera_id:
                inst = Camera.from_manager_output(c)
                inst._controller_id = self._controller_id
                return inst
        return None


@strawberry.type(description="Recording-status wrapper for protect_get_recording_status.")
class RecordingStatusList:
    """Wrapper-dict pass-through for ``{cameras: [...], count}``.

    Per-camera rows (``camera_id, camera_name, recording_mode,
    is_recording, has_recordings, video_stats: {...}``) are
    heterogeneous; surfaced as a JSON sub-map rather than typed rows.
    """

    cameras: strawberry.scalars.JSON | None  # type: ignore[name-defined]
    count: int | None

    _raw: strawberry.Private[dict[str, Any] | None] = None

    @classmethod
    def render_hint(cls, kind: str) -> dict:
        return {"kind": kind}

    @classmethod
    def from_manager_output(cls, obj: Any) -> "RecordingStatusList":
        if isinstance(obj, dict):
            cameras = obj.get("cameras") or []
            count = obj.get("count", len(cameras))
            inst = cls(cameras=cameras, count=count)
            inst._raw = {"cameras": cameras, "count": count}
            return inst
        if hasattr(obj, "model_dump"):
            dumped = obj.model_dump()
            inst = cls(
                cameras=dumped.get("cameras"),
                count=dumped.get("count"),
            )
            inst._raw = dict(dumped)
            return inst
        inst = cls(cameras=[], count=0)
        inst._raw = {"cameras": [], "count": 0}
        return inst

    def to_dict(self) -> dict:
        if self._raw is not None:
            return self._raw
        return {"cameras": [], "count": 0}
