"""AccessQuery — read-only GraphQL resolvers for the UniFi Access product.

Phase 6 PR4 Task C — wires every migrated access read tool into a typed
``query.access.*`` field. Mirrors the ProtectQuery / NetworkQuery shape:

- Fetch helpers route through ``ctx.cache.get_or_fetch`` so concurrent
  resolvers in the same request share a single manager round-trip.
- Page wrappers carry pagination cursors per LIST resolver.
- DETAIL resolvers either filter the cached LIST snapshot by primary key
  (``door``, ``event``, ``user``, ``credential``, ``policy``, ``visitor``,
  ``device``) or fetch per-id via cache when there is no list
  (``doorStatus``, ``activitySummary``, ``systemInfo``, ``health``).

Relationship edges (Door.policy_assignments, User.credentials, Event.door,
Event.user) land in Task D. The ``access`` slot of ``EXEMPT_PRODUCTS`` in
test_graphql_coverage stays set until Task E drops it once edges are in
place.

Access is a single-controller, no-site product: the access connection
manager has no ``set_site`` method. We guard the call with ``getattr`` so
the fetch helpers can be reused if Access ever grows site awareness.
"""

from __future__ import annotations

from typing import Any

import strawberry
from strawberry.types import Info

from unifi_api.graphql.context import GraphQLContext
from unifi_api.graphql.permissions import IsRead
from unifi_api.graphql.types.access.credentials import Credential
from unifi_api.graphql.types.access.devices import AccessDevice
from unifi_api.graphql.types.access.doors import Door, DoorGroup, DoorStatus
from unifi_api.graphql.types.access.events import ActivitySummary, Event
from unifi_api.graphql.types.access.policies import Policy
from unifi_api.graphql.types.access.schedules import Schedule
from unifi_api.graphql.types.access.system import AccessHealth, AccessSystemInfo
from unifi_api.graphql.types.access.users import User
from unifi_api.graphql.types.access.visitors import Visitor

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


# ---------------------------------------------------------------------------
# Key extractors — feed the pagination helper.
# ---------------------------------------------------------------------------


def _id_key(obj: Any) -> tuple:
    return (0, str(_id_of(obj) or ""))


def _event_key(obj: Any) -> tuple:
    """Sort by (timestamp, id) — newest-first ordering is captured by the
    REST routes; paginate() sorts ascending which is fine for cursor stability.
    """
    raw = _raw(obj)
    if isinstance(raw, dict):
        ts = raw.get("timestamp") or raw.get("time") or 0
        rid = raw.get("id") or ""
    else:
        ts = getattr(raw, "timestamp", None) or getattr(raw, "time", None) or 0
        rid = getattr(raw, "id", None) or ""
    return (int(ts or 0), str(rid))


def _visitor_key(obj: Any) -> tuple:
    raw = _raw(obj)
    if isinstance(raw, dict):
        ts = raw.get("created_at") or 0
        rid = raw.get("id") or raw.get("_id") or ""
    else:
        ts = getattr(raw, "created_at", None) or 0
        rid = getattr(raw, "id", None) or getattr(raw, "_id", None) or ""
    return (int(ts or 0), str(rid))


# ---------------------------------------------------------------------------
# Fetch helpers — one per manager-method/key combo.
# ---------------------------------------------------------------------------


async def _fetch_doors(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/doors/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "door_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_doors())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_door_groups(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/door-groups/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "door_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_door_groups())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_door_status(
    ctx: GraphQLContext,
    controller: str,
    door_id: str,
) -> Any:
    key = f"access/door-status/{controller}/{door_id}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "door_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return await mgr.get_door_status(door_id)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_devices(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/devices/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "device_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_devices())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_users(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/users/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_users())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_credentials(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/credentials/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "credential_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_credentials())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_policies(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/policies/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "policy_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_policies())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_schedules(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/schedules/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "policy_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_schedules())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_visitors(ctx: GraphQLContext, controller: str) -> list:
    key = f"access/visitors/{controller}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "visitor_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_visitors())

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_events(
    ctx: GraphQLContext,
    controller: str,
    list_limit: int,
) -> list:
    key = f"access/events/{controller}/{list_limit}"

    async def _do() -> list:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "event_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return list(await mgr.list_events(limit=list_limit))

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_activity_summary(
    ctx: GraphQLContext,
    controller: str,
    door_id: str | None,
    days: int,
) -> Any:
    key = f"access/activity-summary/{controller}/{door_id or ''}/{days}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "event_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return await mgr.get_activity_summary(door_id=door_id, days=days)

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_system_info(ctx: GraphQLContext, controller: str) -> Any:
    key = f"access/system-info/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return await mgr.get_system_info()

    return await ctx.cache.get_or_fetch(key, _do)


async def _fetch_health(ctx: GraphQLContext, controller: str) -> Any:
    key = f"access/health/{controller}"

    async def _do() -> Any:
        async with ctx.sessionmaker() as session:
            mgr = await ctx.manager_factory.get_domain_manager(
                session,
                controller,
                "access",
                "system_manager",
            )
            await ctx.manager_factory.get_connection_manager(
                session,
                controller,
                "access",
            )
            return await mgr.get_health()

    return await ctx.cache.get_or_fetch(key, _do)


# ---------------------------------------------------------------------------
# Page wrappers — one per LIST resolver.
# ---------------------------------------------------------------------------


@strawberry.type(description="Paginated page of UniFi Access doors.")
class DoorPage:
    items: list[Door]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access door groups.")
class DoorGroupPage:
    items: list[DoorGroup]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access devices.")
class AccessDevicePage:
    items: list[AccessDevice]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access users.")
class UserPage:
    items: list[User]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access credentials.")
class CredentialPage:
    items: list[Credential]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access policies.")
class PolicyPage:
    items: list[Policy]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access schedules.")
class SchedulePage:
    items: list[Schedule]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access visitors.")
class VisitorPage:
    items: list[Visitor]
    next_cursor: str | None


@strawberry.type(description="Paginated page of UniFi Access events.")
class AccessEventPage:
    items: list[Event]
    next_cursor: str | None


# ---------------------------------------------------------------------------
# AccessQuery
# ---------------------------------------------------------------------------


@strawberry.type(description="Read-only access to UniFi Access resources.")
class AccessQuery:
    # ---- Doors -----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List doors on the Access controller (paginated).",
    )
    async def doors(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DoorPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_doors(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[Door] = []
        for d in page:
            inst = Door.from_manager_output(d)
            inst._controller_id = str(controller)
            items.append(inst)
        return DoorPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access door by id.",
    )
    async def door(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Door | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_doors(ctx, controller)
        for d in raw:
            if _id_of(d) == id:
                inst = Door.from_manager_output(d)
                inst._controller_id = str(controller)
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access door groups (paginated).",
    )
    async def door_groups(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> DoorGroupPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_door_groups(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return DoorGroupPage(
            items=[DoorGroup.from_manager_output(g) for g in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the live status (lock state + last event) of a door.",
    )
    async def door_status(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> DoorStatus | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_door_status(ctx, controller, id)
        if raw is None:
            return None
        return DoorStatus.from_manager_output(raw)

    # ---- Devices ---------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access devices (readers / hubs / locks, paginated).",
    )
    async def devices(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AccessDevicePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_devices(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return AccessDevicePage(
            items=[AccessDevice.from_manager_output(d) for d in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access device by id.",
    )
    async def device(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> AccessDevice | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_devices(ctx, controller)
        for d in raw:
            if _id_of(d) == id:
                return AccessDevice.from_manager_output(d)
        return None

    # ---- Users -----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access users (employees / cardholders, paginated).",
    )
    async def users(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> UserPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_users(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[User] = []
        for u in page:
            inst = User.from_manager_output(u)
            inst._controller_id = str(controller)
            items.append(inst)
        return UserPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Credentials -----------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access credentials (NFC / PIN / etc., paginated).",
    )
    async def credentials(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> CredentialPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_credentials(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[Credential] = []
        for c in page:
            inst = Credential.from_manager_output(c)
            inst._controller_id = str(controller)
            items.append(inst)
        return CredentialPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access credential by id.",
    )
    async def credential(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Credential | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_credentials(ctx, controller)
        for c in raw:
            if _id_of(c) == id:
                inst = Credential.from_manager_output(c)
                inst._controller_id = str(controller)
                return inst
        return None

    # ---- Policies --------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access policies (who-can-access-what bindings).",
    )
    async def policies(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> PolicyPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_policies(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        items: list[Policy] = []
        for p in page:
            inst = Policy.from_manager_output(p)
            inst._controller_id = str(controller)
            items.append(inst)
        return PolicyPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access policy by id.",
    )
    async def policy(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Policy | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_policies(ctx, controller)
        for p in raw:
            if _id_of(p) == id:
                inst = Policy.from_manager_output(p)
                inst._controller_id = str(controller)
                return inst
        return None

    # ---- Schedules -------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access schedules (weekly access windows).",
    )
    async def schedules(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> SchedulePage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_schedules(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_id_key,
        )
        return SchedulePage(
            items=[Schedule.from_manager_output(s) for s in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    # ---- Visitors --------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access visitors (time-bounded guest passes).",
    )
    async def visitors(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> VisitorPage:
        ctx: GraphQLContext = info.context
        raw = await _fetch_visitors(ctx, controller)

        from unifi_api.services.pagination import paginate

        cursor_obj = _decode_cursor(cursor)
        page, next_cursor = paginate(
            list(raw),
            limit=limit,
            cursor=cursor_obj,
            key_fn=_visitor_key,
        )
        return VisitorPage(
            items=[Visitor.from_manager_output(v) for v in page],
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access visitor by id.",
    )
    async def visitor(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Visitor | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_visitors(ctx, controller)
        for v in raw:
            if _id_of(v) == id:
                return Visitor.from_manager_output(v)
        return None

    # ---- Events / Activity ----------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="List Access events (paginated, most recent first).",
    )
    async def events(
        self,
        info: Info,
        controller: strawberry.ID,
        limit: int = 50,
        cursor: str | None = None,
    ) -> AccessEventPage:
        ctx: GraphQLContext = info.context
        # Mirror the REST route: pull a wider window from the manager so
        # paginate() has enough rows to cursor through.
        raw = await _fetch_events(ctx, controller, max(limit, 100))

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
        return AccessEventPage(
            items=items,
            next_cursor=next_cursor.encode() if next_cursor else None,
        )

    @strawberry.field(
        permission_classes=[IsRead],
        description="Look up a single Access event by id.",
    )
    async def event(
        self,
        info: Info,
        controller: strawberry.ID,
        id: strawberry.ID,
    ) -> Event | None:
        ctx: GraphQLContext = info.context
        # Filter the cached events list — the REST detail endpoint hits a
        # dedicated manager method, but the LIST snapshot is cheaper to
        # reuse for resolver-graph queries.
        raw = await _fetch_events(ctx, controller, 100)
        for e in raw:
            if _id_of(e) == id:
                inst = Event.from_manager_output(e)
                inst._controller_id = str(controller)
                return inst
        return None

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the access activity histogram summary.",
    )
    async def activity_summary(
        self,
        info: Info,
        controller: strawberry.ID,
        door_id: str | None = None,
        days: int = 7,
    ) -> ActivitySummary | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_activity_summary(ctx, controller, door_id, days)
        if raw is None:
            return None
        return ActivitySummary.from_manager_output(raw)

    # ---- System ----------------------------------------------------------

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the Access application info (name + version + host).",
    )
    async def system_info(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> AccessSystemInfo | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_system_info(ctx, controller)
        if raw is None:
            return None
        return AccessSystemInfo.from_manager_output(raw)

    @strawberry.field(
        permission_classes=[IsRead],
        description="Get the Access health probe summary.",
    )
    async def health(
        self,
        info: Info,
        controller: strawberry.ID,
    ) -> AccessHealth | None:
        ctx: GraphQLContext = info.context
        raw = await _fetch_health(ctx, controller)
        if raw is None:
            return None
        return AccessHealth.from_manager_output(raw)
