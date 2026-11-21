"""A loopback stand-in for a UniFi OS console serving InnerSpace.

Shared by the core and app tests; each test package's conftest imports the fixtures by name.

Plain HTTP on 127.0.0.1. Logins issue session ``N`` (cookie ``TOKEN=session-N``)
and a fresh CSRF token ``csrf-N``; any other route first checks both, the way
the console does, and answers an invalid session with 403 ``errors.api.access``
(or 401 when a test asks for it), except ``GET /api/system``, which answers a
missing or invalid session with 200 and a public payload without the app list,
as UniFi OS Server does on InnerSpace 1.4.3. A valid cookie without any ``X-CSRF-Token``
header gets the UniFi OS 403 ``Forbidden`` instead. Scripted replies are served
after that check.

Stateful mode (:meth:`StubConsole.load_project`) keeps an internal project and
serves the internal project read and the write routes from it, with the
behaviour recorded live on InnerSpace 1.4.3: a whole batch is rejected with 400
for a partial update object or a remove that is not a stored object, a create
that reuses a stored id and the removal of a type a shape still uses fail with
500, and nothing changes on any refusal. Scripted replies still win over the
state, so a test can fail one read.
"""

from __future__ import annotations

import asyncio
import json
import math
from collections import defaultdict, deque
from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any

import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from unifi_core.innerspace.managers.connection_manager import (
    ATTENUATION_OBJECT_TYPE_PATH,
    INTEGRATION_PREFIX,
    INTERNAL_PROJECT_PATH,
    PLAN_ORDER_PATH,
    PLAN_PATH_PREFIX,
    SHAPE_CHANGE_PATH,
    SYSTEM_PATH,
    WALL_TYPE_PATH,
    InnerSpaceConnectionManager,
)

HOST = "192.0.2.10"
USERNAME = "synthetic-admin"
PASSWORD = "synthetic-password-0123456789"
LOGIN = "/api/auth/login"
LOGOUT = "/api/auth/logout"
ACCESS_DENIED = {"error": {"code": "errors.api.access", "errors": [], "message": "Headers missing", "type": "access"}}
INVALID_DATA = {"error": {"code": "errors.invalid.data", "type": "schema"}}
UNHANDLED = {"error": {"code": "errors.unhandled"}}
ROUTE_NOT_FOUND = {"error": {"code": "errors.route.notFound"}}
# What /api/system serves without a valid session: console facts, no ``apps.controllers`` list, no cookie.
PUBLIC_SYSTEM = {"name": "Synthetic Console", "hardware": {"shortname": "SYNTH"}, "isSetup": True}
STAMP = "2026-01-02T00:00:00.000Z"
# Keys the console adds or keeps itself; an update may leave them out.
_SERVER_KEYS = frozenset({"createdAt", "updatedAt", "originalPosition", "wallTypeId", "attenuationObjectTypeId"})
_TYPE_ROUTES = {
    WALL_TYPE_PATH: ("wallTypes", "wallTypeId"),
    ATTENUATION_OBJECT_TYPE_PATH: ("attenuationObjectTypes", "attenuationObjectTypeId"),
}


@dataclass
class Recorded:
    method: str
    path: str
    query: list[tuple[str, str]]
    headers: dict[str, str]
    body: Any
    session_ok: bool = True


@dataclass
class StubConsole:
    """Scripted replies per ``(method, path)``, a session check, and a record of what arrived."""

    base_url: str = ""
    requests: list[Recorded] = field(default_factory=list)
    logins: int = 0
    held: int = 0
    streamed: int = 0
    stream_done: asyncio.Event = field(default_factory=asyncio.Event)
    _scripts: dict[tuple[str, str], deque] = field(default_factory=lambda: defaultdict(deque))
    _session: int = 0
    _sessions_issued: int = 0
    _expired_status: int | None = None
    _reject_logins: bool = False
    _hold_until: int = 0
    _release: asyncio.Event = field(default_factory=asyncio.Event)
    _csrf: str | None = None
    _token: str | None = None
    _login_gate: asyncio.Event | None = None
    login_arrived: asyncio.Event = field(default_factory=asyncio.Event)
    project: dict[str, Any] | None = None
    _faults: dict[tuple[str, str], deque] = field(default_factory=lambda: defaultdict(deque))
    _hang_release: asyncio.Event = field(default_factory=asyncio.Event)

    def reply(
        self,
        method: str,
        path: str,
        payload: Any = None,
        *,
        status: int = 200,
        headers: dict[str, str] | None = None,
        delay: float = 0.0,
        body_bytes: bytes | None = None,
        stream: tuple[int, int] | None = None,
        declared: int | None = None,
        gate: tuple[asyncio.Event, asyncio.Event] | None = None,
        times: int = 1,
    ) -> None:
        """``stream=(chunks, size)`` answers chunked, with no Content-Length, and counts bytes sent.

        ``times`` answers that many requests the same way (a read-back that settles reads more than once).

        ``declared`` sends a Content-Length of that many bytes and then no body at all.
        ``gate=(arrived, release)`` sets ``arrived`` when the request is in and answers once ``release`` is set.
        """
        for _ in range(times):
            self._scripts[(method, path)].append(
                (status, payload, headers or {}, delay, body_bytes, stream, declared, gate)
            )

    def refuse(self, method: str, path: str, code: str = "errors.validation") -> None:
        """Answer the next ``method`` ``path`` with InnerSpace's 400 refusal carrying ``code``."""
        self.reply(method, path, {"error": {"code": code}}, status=400)

    def redirect(self, path: str, location: str, *, method: str = "GET") -> None:
        self.reply(method, path, status=302, headers={"Location": location})

    def expire_session(self, status: int = 403) -> None:
        """Make the current session invalid; requests carrying it get ``status``."""
        self._session = 0
        self._expired_status = status

    def reject_logins(self, reject: bool = True) -> None:
        self._reject_logins = reject

    def hold_401_until(self, count: int) -> None:
        """Hold requests refused for their session until ``count`` of them arrived."""
        self._hold_until = count
        self._release = asyncio.Event()

    def rotate_token(self, value: str) -> None:
        """Accept ``value`` as the current session's TOKEN cookie from now on."""
        self._token = value

    def rotate_csrf(self, value: str) -> None:
        """Accept ``value`` as the current session's CSRF token from now on."""
        self._csrf = value

    def hold_logins(self) -> asyncio.Event:
        """Hold every login until the returned event is set; ``login_arrived`` is set when one arrives."""
        self._login_gate = asyncio.Event()
        return self._login_gate

    def calls(self, method: str, path: str) -> list[Recorded]:
        return [request for request in self.requests if (request.method, request.path) == (method, path)]

    # ------------------------------------------------------------------
    # Stateful mode
    # ------------------------------------------------------------------

    def load_project(self, state: dict[str, Any]) -> None:
        """Serve the internal project and the write routes from a copy of ``state``.

        ``state`` is the ``data`` member of the internal project read: ``project``,
        ``plans``, ``shapes``, ``products``, ``planScales``, ``wallTypes`` and
        ``attenuationObjectTypes``.
        """
        self.project = deepcopy(state)

    def script_write(self, *, version: str | None = "1.4.3", floor_plans: list[dict[str, Any]] | None = None) -> None:
        """Script the reads a write checks first: ``/api/system`` with ``version``, then the floor plans if given."""
        entry: dict[str, Any] = {"name": "innerspace", "isInstalled": True, "isRunning": True}
        if version is not None:
            entry["version"] = version
        self.reply("GET", SYSTEM_PATH, {"apps": {"controllers": [entry]}})
        if floor_plans is not None:
            self.reply("GET", f"{INTEGRATION_PREFIX}/floor_plans", {"floor_plans": floor_plans})

    def writes(self) -> list[Recorded]:
        """Every request that is not a read, a login or a logout, in arrival order."""
        return [r for r in self.requests if r.method != "GET" and r.path not in (LOGIN, LOGOUT)]

    def shape_changes(self) -> list[Any]:
        """The bodies of every ``shape/change`` request, in arrival order."""
        return [r.body for r in self.calls("POST", SHAPE_CHANGE_PATH)]

    def assert_csrf(self) -> None:
        """Every write carried a session cookie and CSRF token that were valid when it arrived."""
        writes = self.writes()
        assert writes, "no write arrived"
        for write in writes:
            assert write.session_ok, f"{write.method} {write.path} arrived without a valid session and CSRF token"

    def apply_then_hang(self, method: str, path: str) -> None:
        """The next ``method path`` is applied to the state, then never answered until teardown."""
        self._faults[(method, path)].append(("hang", None))

    def drop_connection(self, method: str, path: str, *, apply: bool = True) -> None:
        """The next ``method path`` is applied (or not) and its connection closed without an answer."""
        self._faults[(method, path)].append(("drop", apply))

    def mixed_batch(self, keep: int) -> None:
        """The next ``shape/change`` applies only its first ``keep`` items and answers 200."""
        self._faults[("POST", SHAPE_CHANGE_PATH)].append(("mixed", keep))

    def release_hangs(self) -> None:
        self._hang_release.set()

    async def _stateful(self, request: web.Request, path: str, body: Any) -> web.StreamResponse | None:
        """Serve ``request`` from the project state, or ``None`` when the route is not a stateful one."""
        handler = self._handler(request.method, path)
        if handler is None:
            return None
        faults = self._faults[(request.method, path)]
        fault, option = faults.popleft() if faults else (None, None)
        if fault == "drop":
            if option:
                handler(body, None)
            assert request.transport is not None
            request.transport.close()
            return web.Response()
        response = handler(body, option if fault == "mixed" else None)
        if fault == "hang":
            await self._hang_release.wait()
        return response

    def _handler(self, method: str, path: str) -> Any:
        if (method, path) == ("GET", INTERNAL_PROJECT_PATH):
            return lambda body, keep: web.json_response({"data": deepcopy(self.project)})
        if (method, path) == ("POST", SHAPE_CHANGE_PATH):
            return self._shape_change
        if method == "POST" and path in _TYPE_ROUTES:
            key, reference = _TYPE_ROUTES[path]
            return lambda body, keep: self._type_change(body, key, reference)
        if (method, path) == ("PATCH", PLAN_ORDER_PATH):
            return lambda body, keep: self._plan_order(body)
        if method == "PATCH" and path.startswith(f"{PLAN_PATH_PREFIX}/"):
            plan_id = path[len(PLAN_PATH_PREFIX) + 1 :]
            return lambda body, keep: self._plan_patch(plan_id, body)
        if (method, path) == ("PATCH", INTERNAL_PROJECT_PATH):
            return lambda body, keep: self._project_patch(body)
        return None

    def _shape_change(self, body: Any, keep: int | None) -> web.Response:
        if not isinstance(body, dict) or body.get("mode") != "2D":
            return web.json_response(INVALID_DATA, status=400)
        batches = {kind: body.get(kind, []) for kind in ("create", "update", "remove")}
        if not all(_objects_with_ids(items) for items in batches.values()):
            return web.json_response(INVALID_DATA, status=400)
        stored = {shape["id"]: shape for shape in self.project["shapes"]}
        if not all(_valid_new_shape(item) for item in batches["create"]):
            return web.json_response(INVALID_DATA, status=400)
        if not all(_full_object(item, stored.get(item["id"])) for item in batches["update"] + batches["remove"]):
            return web.json_response(INVALID_DATA, status=400)
        created = [item["id"] for item in batches["create"]]
        if len(set(created)) != len(created) or any(shape_id in stored for shape_id in created):
            return web.json_response(UNHANDLED, status=500)
        operations = [(kind, item) for kind in ("create", "update", "remove") for item in batches[kind]]
        for kind, item in operations if keep is None else operations[:keep]:
            _apply_shape(kind, item, stored)
        self.project["shapes"] = list(stored.values())
        self._recompute_plan_scales()
        empty = {"create": [], "update": [], "remove": []}
        return web.json_response({"data": {"shapes": empty, "products": empty}})

    def _recompute_plan_scales(self) -> None:
        """``planScales[plan]``: the scale line's length in plan units over its metres, and its height."""
        scales: dict[str, Any] = {}
        for shape in self.project["shapes"]:
            if shape.get("type") == "scale" and isinstance(shape.get("planId"), str):
                a, b = shape["position"][:2]
                line = math.hypot(b["x"] - a["x"], b["y"] - a["y"])
                scales[shape["planId"]] = {"scale": line / shape["scale"], "height": shape.get("height")}
        self.project["planScales"] = scales

    def _type_change(self, body: Any, key: str, reference: str) -> web.Response:
        if not isinstance(body, dict):
            return web.json_response(INVALID_DATA, status=400)
        batches = {kind: body.get(kind, []) for kind in ("create", "update", "remove")}
        if not all(_objects_with_ids(items) for items in batches.values()):
            return web.json_response(INVALID_DATA, status=400)
        types = {row["id"]: row for row in self.project.setdefault(key, [])}
        if not all(_full_object(item, types.get(item["id"])) for item in batches["update"]):
            return web.json_response(INVALID_DATA, status=400)
        created = [item["id"] for item in batches["create"]]
        if len(set(created)) != len(created) or any(type_id in types for type_id in created):
            return web.json_response(UNHANDLED, status=500)
        in_use = {shape.get(reference) for shape in self.project["shapes"]}
        if any(item["id"] in in_use for item in batches["remove"]):
            return web.json_response(UNHANDLED, status=500)
        for item in batches["create"] + batches["update"]:
            types[item["id"]] = deepcopy(item)
        for item in batches["remove"]:
            types.pop(item["id"], None)
        self.project[key] = list(types.values())
        return web.json_response({"data": {}})

    def _plan_order(self, body: Any) -> web.Response:
        plans = {plan["id"]: plan for plan in self.project["plans"]}
        if not isinstance(body, list) or not all(
            isinstance(item, dict) and item.get("id") in plans and isinstance(item.get("ordering"), int)
            for item in body
        ):
            return web.json_response(INVALID_DATA, status=400)
        for item in body:
            plans[item["id"]]["ordering"] = item["ordering"]
        return web.json_response({"data": {"plans": deepcopy(self.project["plans"])}})

    def _plan_patch(self, plan_id: str, body: Any) -> web.Response:
        plan = next((p for p in self.project["plans"] if p["id"] == plan_id), None)
        if plan is None:
            return web.json_response(ROUTE_NOT_FOUND, status=404)
        if not isinstance(body, dict) or len(body) != 1:
            return web.json_response(INVALID_DATA, status=400)
        ((name, value),) = body.items()
        title_ok = name == "title" and isinstance(value, str) and 1 <= len(value.strip()) <= 32
        attenuation_ok = name == "attenuation" and (value is None or isinstance(value, (int, float)))
        if not (title_ok or attenuation_ok):
            return web.json_response(INVALID_DATA, status=400)
        plan[name] = value.strip() if title_ok else value
        # The console answers with the plan and every shape and product of the project.
        data = {"plan": plan, "shapes": self.project["shapes"], "products": self.project.get("products", [])}
        return web.json_response({"data": deepcopy(data)})

    def _project_patch(self, body: Any) -> web.Response:
        if not isinstance(body, dict) or set(body) != {"unit"} or body["unit"] not in ("metric", "imperial"):
            return web.json_response(INVALID_DATA, status=400)
        self.project["project"]["unit"] = body["unit"]
        return web.json_response({})

    # ------------------------------------------------------------------
    # Dispatch
    # ------------------------------------------------------------------

    async def handle(self, request: web.Request) -> web.StreamResponse:
        raw = await request.read()
        try:
            body = json.loads(raw) if raw else None
        except ValueError:
            body = raw
        path = request.raw_path.split("?")[0]
        recorded = Recorded(request.method, path, list(request.query.items()), dict(request.headers), body)
        self.requests.append(recorded)
        script = self._scripts[(request.method, path)]
        if path == LOGIN:
            self.logins += 1
            if self._login_gate is not None:
                self.login_arrived.set()
                await self._login_gate.wait()
            if script:
                return await self._scripted(request, script)
            return self._login(body)
        if self._csrf_missing(request):
            recorded.session_ok = False
            return web.Response(status=403, text="Forbidden")
        if not self._session_valid(request):
            recorded.session_ok = False
            return await self._refuse_session(
                hold=path != LOGOUT, public=(request.method, path) == ("GET", SYSTEM_PATH)
            )
        if path == LOGOUT and not script:
            self._session = 0
            return web.json_response({})
        if script:
            return await self._scripted(request, script)
        if self.project is not None:
            response = await self._stateful(request, path, body)
            if response is not None:
                return response
        return web.json_response({"code": "UNSCRIPTED"}, status=599)

    def _csrf_missing(self, request: web.Request) -> bool:
        """A valid session cookie without any CSRF header: UniFi OS refuses it before InnerSpace sees it."""
        return (
            bool(self._session)
            and "X-CSRF-Token" not in request.headers
            and request.cookies.get("TOKEN") == (self._token or f"session-{self._session}")
        )

    async def _stream(
        self, request: web.Request, status: int, headers: dict[str, str], chunks: int, size: int
    ) -> web.StreamResponse:
        response = web.StreamResponse(status=status, headers=headers)
        response.enable_chunked_encoding()
        await response.prepare(request)
        try:
            for _ in range(chunks):
                await response.write(b"\x00" * size)
                self.streamed += size
        except ConnectionError:
            pass
        finally:
            self.stream_done.set()
        return response

    def _login(self, body: Any) -> web.Response:
        if self._reject_logins:
            # A console that echoes what it was sent: the client must never repeat it.
            return web.json_response({"error": {"code": "AUTHENTICATION_FAILED", "echo": body}}, status=401)
        self._sessions_issued += 1
        self._session = self._sessions_issued
        self._expired_status = None
        self._csrf = None
        self._token = None
        response = web.json_response({"unique_id": "synthetic-user"})
        response.set_cookie("TOKEN", f"session-{self._session}")
        response.headers["X-Csrf-Token"] = f"csrf-{self._session}"
        return response

    def _session_valid(self, request: web.Request) -> bool:
        return bool(self._session) and (
            request.cookies.get("TOKEN") == (self._token or f"session-{self._session}")
            and request.headers.get("X-CSRF-Token") == (self._csrf or f"csrf-{self._session}")
        )

    async def _refuse_session(self, *, hold: bool, public: bool = False) -> web.Response:
        status = self._expired_status or 403
        if hold and self._hold_until:
            self.held += 1
            if self.held >= self._hold_until:
                self._release.set()
            await self._release.wait()
        if public:
            return web.json_response(PUBLIC_SYSTEM)
        if status == 401:
            return web.json_response({"error": {"code": "errors.api.unauthorized"}}, status=401)
        return web.json_response(ACCESS_DENIED, status=status)

    async def _scripted(self, request: web.Request, script: deque) -> web.StreamResponse:
        status, payload, headers, delay, body_bytes, stream, declared, gate = script.popleft()
        if gate is not None:
            arrived, release = gate
            arrived.set()
            await release.wait()
        if delay:
            await asyncio.sleep(delay)
        if declared is not None:
            response = web.StreamResponse(status=status, headers=headers)
            response.content_length = declared
            await response.prepare(request)
            return response
        if stream:
            return await self._stream(request, status, headers, *stream)
        if body_bytes is not None:
            return web.Response(status=status, headers=headers, body=body_bytes)
        if payload is None:
            return web.Response(status=status, headers=headers)
        return web.json_response(payload, status=status, headers=headers)


def _objects_with_ids(items: Any) -> bool:
    """A list of objects with string ids; a bare id string rejects the whole batch (400)."""
    return isinstance(items, list) and all(isinstance(item, dict) and isinstance(item.get("id"), str) for item in items)


def _valid_new_shape(item: dict[str, Any]) -> bool:
    if not all(key in item for key in ("type", "projectId", "planId", "position")):
        return False
    position = item["position"]
    if item["type"] == "attenuationObject":
        # The polygon must be closed: the last point repeats the first.
        return isinstance(position, list) and len(position) >= 4 and position[0] == position[-1]
    if item["type"] == "scale":
        return "computedScale" in item
    return True


def _full_object(item: dict[str, Any], stored: dict[str, Any] | None) -> bool:
    """Whether ``item`` carries every key of the stored object (the console rejects partial objects)."""
    return stored is not None and not (set(stored) - _SERVER_KEYS - set(item))


def _apply_shape(kind: str, item: dict[str, Any], stored: dict[str, dict[str, Any]]) -> None:
    if kind == "remove":
        stored.pop(item["id"], None)
        return
    shape = deepcopy(item)
    shape["updatedAt"] = STAMP
    shape["createdAt"] = STAMP if kind == "create" else stored[item["id"]].get("createdAt")
    if shape.get("type") == "wall":
        shape.setdefault("originalPosition", None)
        # A wall sent without wallTypeId (custom to built-in) is stored with null.
        shape.setdefault("wallTypeId", None)
    if shape.get("type") == "attenuationObject":
        shape.setdefault("attenuationObjectTypeId", None)
    stored[item["id"]] = shape


async def start_stub(port: int | None = None) -> tuple[StubConsole, TestServer]:
    """Start the stub on a free loopback port, or on ``port`` (one a test found closed)."""
    stub = StubConsole()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", stub.handle)
    server = TestServer(app, host="127.0.0.1", port=port)
    await server.start_server()
    stub.base_url = str(server.make_url("")).rstrip("/")
    return stub, server


@pytest.fixture
async def console(monkeypatch):
    # A write's read-back settle waits are instant here: every connection manager built in a test
    # sleeps with a no-op. Tests of the waits replace it with a recording sleep.
    from unifi_core.innerspace.managers import connection_manager

    async def no_wait(_seconds: float) -> None:
        return None

    monkeypatch.setattr(connection_manager.InnerSpaceConnectionManager, "readback_sleep", staticmethod(no_wait))
    stub, server = await start_stub()
    yield stub
    stub.release_hangs()
    await server.close()


@pytest.fixture
async def manager(console):
    cm = InnerSpaceConnectionManager(HOST, USERNAME, PASSWORD, base_url=console.base_url)
    yield cm
    await cm.close()


@pytest.fixture
async def connected(manager):
    assert await manager.initialize() is True
    return manager
