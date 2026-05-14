"""ProtectQuery — read-only GraphQL resolvers for the UniFi Protect product.

Phase 6 PR3 Task D — wires every migrated protect read tool into a typed
``query.protect.*`` field. Mirrors the NetworkQuery shape:

- Fetch helpers route through ``ctx.cache.get_or_fetch`` so concurrent
  resolvers in the same request share a single manager round-trip.
- Page wrappers carry pagination cursors per LIST resolver.
- DETAIL resolvers either filter the cached LIST snapshot by primary key
  (``camera``, ``event`` -> events list, ``recording`` -> per-camera list)
  or fetch per-id via cache when there is no list (``snapshot``,
  ``cameraAnalytics``, ``cameraStreams``, ``eventThumbnail``).
- Wrapper-dict tools (``alarmStatus``, ``alarmProfiles``,
  ``recordingStatus``, ``viewers``) return the typed wrapper directly via
  ``Type.from_manager_output(raw)``.

Relationship edges (Camera.events, Camera.recordings, Liveview.cameras,
Recording.camera) land in Task E. The ``protect`` slot of
``EXEMPT_PRODUCTS`` in test_graphql_coverage stays set until Task F drops
it once edges are in place.

Protect is a single-controller, no-site product: the protect connection
manager has no ``set_site`` method. We guard the call with ``getattr`` so
the fetch helpers can be reused if Protect ever grows site awareness.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.protect.alarms import AlarmProfileList, AlarmStatus
from unifi_api.graphql.types.protect.cameras import (
    Camera,
    CameraAnalytics,
    CameraStreams,
    Snapshot,
)
from unifi_api.graphql.types.protect.chimes import Chime
from unifi_api.graphql.types.protect.events import (
    Event,
    EventThumbnail,
    SmartDetection,
)
from unifi_api.graphql.types.protect.lights import Light
from unifi_api.graphql.types.protect.liveviews import Liveview
from unifi_api.graphql.types.protect.recognition import KnownFace
from unifi_api.graphql.types.protect.recordings import (
    Recording,
    RecordingStatusList,
)
from unifi_api.graphql.types.protect.sensors import Sensor
from unifi_api.graphql.types.protect.system import (
    FirmwareStatus,
    ProtectHealth,
    ProtectSystemInfo,
    ViewerList,
)

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _raw(obj: Any) -> Any:
    raw = getattr(obj, "raw", None)
    if isinstance(raw, dict):
        return raw
    if isinstance(obj, dict):
        return obj
    return obj


def _id_of(obj: Any) -> Any:
    raw = _raw(obj)
    if isinstance(raw, dict):
        return raw.get("id") or raw.get("_id")
    return getattr(raw, "id", None) or getattr(raw, "_id", None)


def _decode_cursor(cursor: str | None):
    """Translate an opaque cursor string to a Cursor (or raise ValueError)."""
    from unifi_api.services.pagination import Cursor, InvalidCursor

    if not cursor:
        return None
    try:
        return Cursor.decode(cursor)
    except InvalidCursor:
        raise ValueError("invalid cursor")


async def _maybe_set_site(cm: Any, site: str | None) -> None:
    """Call cm.set_site(site) only if the CM exposes it AND a site arg given.

    Protect's connection manager is single-controller-no-site; this helper
    keeps the fetch helpers symmetric with NetworkQuery.
    """
    if site is None:
        return
    set_site = getattr(cm, "set_site", None)
    if set_site is None:
        return
    if getattr(cm, "site", None) != site:
        await set_site(site)


# ---------------------------------------------------------------------------
# Key extractors — feed the pagination helper.
# ---------------------------------------------------------------------------


def _id_key(obj: Any) -> tuple:
    return (0, str(_id_of(obj) or ""))


def _ts_to_int(ts: Any) -> int:
    """Coerce a Protect timestamp to an integer for sort-key comparison.

    UniFi Protect returns timestamps as Unix epoch milliseconds (int) in
    older firmware and as ISO-8601 strings in newer builds.  Accept both.
    """
    if ts is None:
        return 0
    if isinstance(ts, (int, float)):
        return int(ts)
    s = str(ts).strip()
    if not s:
        return 0
    # Fast path: plain integer string
    if s.lstrip("-").isdigit():
        return int(s)
    # ISO-8601 string — convert to epoch milliseconds
    try:
        from datetime import datetime

        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        return int(dt.timestamp() * 1000)
    except ValueError:
        return 0


def _event_key(obj: Any) -> tuple:
    """Sort by (start, id) descending (paginate sorts ascending; Protect
    routes already sort desc upstream — this reproduces a stable order).

    Handles both integer-epoch-ms and ISO-8601 timestamp formats.
    """
    raw = _raw(obj)
    if isinstance(raw, dict):
        ts = raw.get("start")
        rid = raw.get("id") or ""
    else:
        ts = getattr(raw, "start", None)
        rid = getattr(raw, "id", None) or ""
    return (_ts_to_int(ts), str(rid))


def _recording_key(obj: Any) -> tuple:
    raw = _raw(obj)
    if isinstance(raw, dict):
        ts = raw.get("start")
        rid = raw.get("id") or ""
    else:
        ts = getattr(raw, "start", None)
        rid = getattr(raw, "id", None) or ""
    return (_ts_to_int(ts), str(rid))


# ---------------------------------------------------------------------------
# Fetch helpers — one per manager-method/key combo.
# ---------------------------------------------------------------------------


async def _fetch_cameras(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/cameras/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "camera_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_cameras())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_camera_analytics(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str,
) -> Any:
    key = f"protect/camera-analytics/{controller}/{camera_id}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "camera_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_camera_analytics(camera_id)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_camera_streams(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str,
) -> Any:
    key = f"protect/camera-streams/{controller}/{camera_id}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "camera_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_camera_streams(camera_id)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_known_faces(
    ctx: GraphQLContext,
    controller: str,
    min_confidence: int,
    include_interest: bool,
    group_types: list[str] | None,
    order_by: str,
    order_direction: str,
) -> list:
    group_types_key = ",".join(group_types) if group_types else ""
    key = (
        f"protect/known-faces/{controller}/{min_confidence}/"
        f"{include_interest}/{group_types_key}/{order_by}/{order_direction}"
    )

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "recognition_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            result = await mgr.list_known_faces(
                page_size=1000,
                min_confidence=min_confidence,
                include_interest=include_interest,
                group_types=group_types,
                order_by=order_by,
                order_direction=order_direction,
            )
            return list(result.get("faces", []))

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_snapshot(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str,
    width: int | None,
    height: int | None,
) -> Any:
    key = f"protect/snapshot/{controller}/{camera_id}/{width}/{height}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "camera_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_snapshot(camera_id, width=width, height=height)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_chimes(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/chimes/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "chime_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_chimes())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_alarm_status(ctx: GraphQLContext, controller: str) -> Any:
    key = f"protect/alarm-status/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "alarm_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_arm_state()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_alarm_profiles(ctx: GraphQLContext, controller: str) -> Any:
    key = f"protect/alarm-profiles/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "alarm_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.list_arm_profiles()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_events(
    ctx: GraphQLContext,
    controller: str,
    event_type: str | None,
    camera_id: str | None,
    list_limit: int,
) -> list:
    key = f"protect/events/{controller}/{event_type or ''}/{camera_id or ''}/{list_limit}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "event_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(
                await mgr.list_events(
                    event_type=event_type,
                    camera_id=camera_id,
                    limit=list_limit,
                )
            )

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_event_thumbnail(
    ctx: GraphQLContext,
    controller: str,
    event_id: str,
    width: int | None,
    height: int | None,
) -> Any:
    key = f"protect/event-thumbnail/{controller}/{event_id}/{width}/{height}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "event_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_event_thumbnail(
                event_id,
                width=width,
                height=height,
            )

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_smart_detections(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str | None,
    detection_type: str | None,
    min_confidence: int | None,
    list_limit: int,
) -> list:
    key = (
        f"protect/smart-detections/{controller}/{camera_id or ''}/{detection_type or ''}/{min_confidence}/{list_limit}"
    )

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "event_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(
                await mgr.list_smart_detections(
                    camera_id=camera_id,
                    detection_type=detection_type,
                    min_confidence=min_confidence,
                    limit=list_limit,
                )
            )

    return await ctx.cache.get_or_fetch(key, _do)


def _normalize_recordings(result: Any) -> list[dict]:
    """Coerce the recording manager's response into a list of dicts.

    ``RecordingManager.list_recordings`` historically returns a single dict
    (the per-camera continuous recording window); newer/test stubs may
    return a list. Mirrors the REST route's handling.
    """
    if isinstance(result, list):
        return result
    if isinstance(result, dict):
        return [result]
    return []


async def _fetch_recordings(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str,
) -> list[dict]:
    key = f"protect/recordings/{controller}/{camera_id}"

    async def _do() -> list[dict]:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "recording_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            result = await mgr.list_recordings(camera_id=camera_id)
            return _normalize_recordings(result)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_recording_status(
    ctx: GraphQLContext,
    controller: str,
    camera_id: str | None,
) -> Any:
    key = f"protect/recording-status/{controller}/{camera_id or ''}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "recording_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_recording_status(camera_id=camera_id)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_lights(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/lights/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "light_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_lights())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_sensors(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/sensors/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "sensor_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_sensors())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_liveviews(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/liveviews/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "liveview_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_liveviews())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_system_info(ctx: GraphQLContext, controller: str) -> Any:
    key = f"protect/system-info/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_system_info()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_health(ctx: GraphQLContext, controller: str) -> Any:
    key = f"protect/health/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_health()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_firmware_status(ctx: GraphQLContext, controller: str) -> Any:
    key = f"protect/firmware-status/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return await mgr.get_firmware_status()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_viewers(ctx: GraphQLContext, controller: str) -> list:
    key = f"protect/viewers/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "protect",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "protect",
            )
            return list(await mgr.list_viewers())

    return await ctx.cache.get_or_fetch(key, _do)


# ---------------------------------------------------------------------------
# Page wrappers — one per LIST resolver.
# ---------------------------------------------------------------------------


@strawberry.type(description="Paginated page of UniFi Protect cameras.")
class CameraPage:
    items: list[Camera]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect chimes.")
class ChimePage:
    items: list[Chime]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect events.")
class EventPage:
    items: list[Event]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect smart-detections.")
class SmartDetectionPage:
    items: list[SmartDetection]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect recording windows.")
class RecordingPage:
    items: list[Recording]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect lights.")
class LightPage:
    items: list[Light]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect sensors.")
class SensorPage:
    items: list[Sensor]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect liveviews.")
class LiveviewPage:
    items: list[Liveview]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Protect Known Faces.")
class KnownFacePage:
    items: list[KnownFace]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# ProtectQuery
# ---------------------------------------------------------------------------


@strawberry.type(description="Read-only access to UniFi Protect resources.")
class ProtectQuery:
    # ---- Cameras ---------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List cameras on the Protect controller (paginated).",
    )
    async def cameras(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CameraPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_cameras(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[Camera] = []
        for c in page:
            inst = Camera.from_manager_output(c)
            inst._controller_id = str(controller)
            items.append(inst)
        return CameraPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Protect camera by id.",
    )
    async def camera(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Camera | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_cameras(ctx, controller)
        for c in raw:
            if _id_of(c) == id:
                inst = Camera.from_manager_output(c)
                inst._controller_id = str(controller)
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get analytics summary for a Protect camera.",
    )
    async def camera_analytics(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> CameraAnalytics | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_camera_analytics(ctx, controller, id)
        if raw is None:
            return None
        return CameraAnalytics.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the stream catalog (channels + RTSPS URLs) for a camera.",
    )
    async def camera_streams(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> CameraStreams | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_camera_streams(ctx, controller, id)
        if raw is None:
            return None
        return CameraStreams.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Capture a JPEG snapshot from a camera (metadata only).",
    )
    async def snapshot(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
        width: int | None = None,
        height: int | None = None,
    ) -> Snapshot | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_snapshot(ctx, controller, id, width, height)
        if raw is None:
            return None
        return Snapshot.from_manager_output(raw)

    # ---- Recognition -----------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List assigned Protect Known Faces / named face recognition groups.",
    )
    async def known_faces(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
        min_confidence: int = 30,
        include_interest: bool = True,
        group_types: list[str] | None = None,
        order_by: str = "name",
        order_direction: str = "asc",
    ) -> KnownFacePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_known_faces(
            ctx,
            str(controller),
            min_confidence,
            include_interest,
            group_types,
            order_by,
            order_direction,
        )

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return KnownFacePage(
            items=[KnownFace.from_manager_output(face) for face in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Chimes ----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List paired Protect chimes (paginated).",
    )
    async def chimes(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> ChimePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_chimes(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return ChimePage(
            items=[Chime.from_manager_output(c) for c in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Alarms ----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the alarm system arm-state snapshot.",
    )
    async def alarm_status(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> AlarmStatus | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_alarm_status(ctx, controller)
        if raw is None:
            return None
        return AlarmStatus.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="List configured alarm profiles ({profiles, count}).",
    )
    async def alarm_profiles(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> AlarmProfileList | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_alarm_profiles(ctx, controller)
        if raw is None:
            return None
        return AlarmProfileList.from_manager_output(raw)

    # ---- Events ----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Protect events (paginated, most recent first).",
    )
    async def events(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
        event_type: str | None = None,
        camera_id: str | None = None,
    ) -> EventPage:
        ctx: GraphQLContext = info.context
        # Mirror the REST route: pull a wider window from the manager so
        # paginate() has enough rows to cursor through.
        raw = await _fetch_events(
            ctx,
            controller,
            event_type,
            camera_id,
            max(limit, 100),
        )

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_event_key,
        )
        items: list[Event] = []
        for e in page:
            inst = Event.from_manager_output(e)
            inst._controller_id = str(controller)
            items.append(inst)
        return EventPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Protect event by id.",
    )
    async def event(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Event | None:
        ctx: GraphQLContext = info.context
        # Filter the cached events list (no per-id manager call exposed here
        # — the REST detail endpoint hits a dedicated manager method, but
        # the LIST snapshot is cheaper to reuse for resolver-graph queries).
        raw = await _fetch_events(ctx, controller, None, None, 100)
        for e in raw:
            if _id_of(e) == id:
                inst = Event.from_manager_output(e)
                inst._controller_id = str(controller)
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the thumbnail for a Protect event.",
    )
    async def event_thumbnail(
        self,
        info: Info,
        controller: strawberry.ID,
        event_id: strawberry.ID,
        width: int | None = None,
        height: int | None = None,
    ) -> EventThumbnail | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_event_thumbnail(
            ctx,
            controller,
            event_id,
            width,
            height,
        )
        if raw is None:
            return None
        return EventThumbnail.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description=("List Protect smart-detection events (paginated, most recent first)."),
    )
    async def smart_detections(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
        camera_id: str | None = None,
        detection_type: str | None = None,
        min_confidence: int | None = None,
    ) -> SmartDetectionPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_smart_detections(
            ctx,
            controller,
            camera_id,
            detection_type,
            min_confidence,
            max(limit, 100),
        )

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_event_key,
        )
        return SmartDetectionPage(
            items=[SmartDetection.from_manager_output(e) for e in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Recordings ------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description=(
            "List Protect recording windows for a camera. UniFi Protect "
            "exposes a single continuous recording window per camera."
        ),
    )
    async def recordings(
        self,
        info: Info,
        controller: strawberry.ID,
        camera_id: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> RecordingPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_recordings(ctx, controller, camera_id)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_recording_key,
        )
        items: list[Recording] = []
        for r in page:
            inst = Recording.from_manager_output(r)
            inst._controller_id = str(controller)
            inst._camera_id = str(camera_id)
            items.append(inst)
        return RecordingPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description=("Get current recording state for one or all cameras ({cameras, count})."),
    )
    async def recording_status(
        self,
        info: Info,
        controller: strawberry.ID,
        camera_id: str | None = None,
    ) -> RecordingStatusList | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_recording_status(ctx, controller, camera_id)
        if raw is None:
            return None
        return RecordingStatusList.from_manager_output(raw)

    # ---- Lights / Sensors / Liveviews -----------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Protect lights (PIR-triggered floodlights).",
    )
    async def lights(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> LightPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_lights(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return LightPage(
            items=[Light.from_manager_output(c) for c in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Protect sensors (motion / leak / temperature).",
    )
    async def sensors(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> SensorPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_sensors(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return SensorPage(
            items=[Sensor.from_manager_output(c) for c in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Protect liveviews (multi-camera grid layouts).",
    )
    async def liveviews(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> LiveviewPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_liveviews(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[Liveview] = []
        for lv in page:
            inst = Liveview.from_manager_output(lv)
            inst._controller_id = str(controller)
            items.append(inst)
        return LiveviewPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- System ----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the NVR-level system info snapshot.",
    )
    async def system_info(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> ProtectSystemInfo | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_system_info(ctx, controller)
        if raw is None:
            return None
        return ProtectSystemInfo.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the NVR health snapshot (cpu / memory / storage).",
    )
    async def health(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> ProtectHealth | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_health(ctx, controller)
        if raw is None:
            return None
        return ProtectHealth.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get firmware status for the NVR plus its devices.",
    )
    async def firmware_status(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> FirmwareStatus | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_firmware_status(ctx, controller)
        if raw is None:
            return None
        return FirmwareStatus.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Protect viewers ({viewers, count}).",
    )
    async def viewers(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> ViewerList | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_viewers(ctx, controller)
        if raw is None:
            return None
        return ViewerList.from_manager_output(raw)
