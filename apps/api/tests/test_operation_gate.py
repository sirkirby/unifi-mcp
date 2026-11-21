"""The API server orders writes and caps reads per controller application.

Requests go through the real app: the action endpoint's dispatch, a resource
route and GraphQL, with the real ManagerFactory. Only its connection
construction and its domain-manager builders are replaced, by a fake
controller that records how calls overlap.
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.auth.api_key import generate_key, hash_key
from unifi_api.config import ApiConfig, DbConfig, GateConfig, HttpConfig, LoggingConfig, _gate_config, load_config
from unifi_api.db.crypto import ColumnCipher, derive_key
from unifi_api.db.models import ApiKey, AuditLog, Base, Controller
from unifi_api.server import create_app
from unifi_api.services.controllers import ControllerNotFound
from unifi_api.services.operation_gate import (
    RequestAlreadyFinished,
    _RequestReadScope,
    configure_gate_settings,
    gate_for,
    hold_controller_read_slots,
)
from unifi_core.operation_gate import (
    ControllerBusyError,
    GateKey,
    GateSettings,
    OperationGate,
    gate_registry,
    reset_gate_registry_for_tests,
)


class FakeAccessController:
    """Door manager and connection manager standing in for one Access controller."""

    def __init__(self, cid: str) -> None:
        self.cid = cid
        self.writes: list[str] = []
        self.writing = 0
        self.write_overlap = False
        self.reading = 0
        self.read_peak = 0
        self.nested_slots: list[int] = []
        self.hold: asyncio.Event | None = None
        self.hang = False

    async def apply_lock_door(self, door_id: str) -> dict:
        self.writing += 1
        self.write_overlap |= self.writing > 1
        self.writes.append(door_id)
        if self.hang:
            await asyncio.Event().wait()  # a controller that never answers
        if self.hold is not None:
            await self.hold.wait()
        for _ in range(3):
            await asyncio.sleep(0)
        self.writing -= 1
        return {"door_id": door_id, "locked": True}

    async def list_doors(self, compact: bool = False) -> list:
        self.reading += 1
        self.read_peak = max(self.read_peak, self.reading)
        gate = gate_for(self.cid, "access")
        # A read nested in the handler passes through: still one slot for this request.
        async with gate.read():
            self.nested_slots.append(gate.snapshot()["reads_in_use"])
        if self.hold is not None:
            await self.hold.wait()
        await asyncio.sleep(0.01)
        self.reading -= 1
        return []


async def _bootstrap(tmp_path: Path, monkeypatch, *, settings: GateSettings) -> tuple:
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    reset_gate_registry_for_tests()
    config = ApiConfig(
        http=HttpConfig(host="127.0.0.1", port=8080, cors_origins=()),
        logging=LoggingConfig(level="WARNING"),
        db=DbConfig(path=str(tmp_path / "state.db")),
        gate=GateConfig(
            write_hold_seconds=max(settings.hold_budget_seconds, 10),
            call_wait_seconds=max(settings.direct_call_wait_seconds, 1),
            read_concurrency=settings.read_cap,
        ),
    )
    app = create_app(config)
    # Finer limits than the config allows, for a fast test.
    configure_gate_settings(settings)
    async with app.state.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    cid = str(uuid.uuid4())
    material = generate_key()
    cipher = ColumnCipher(derive_key("k"))
    async with app.state.sessionmaker() as session:
        session.add(
            ApiKey(
                id=str(uuid.uuid4()),
                prefix=material.prefix,
                hash=hash_key(material.plaintext),
                scopes="admin",
                name="t",
                created_at=datetime.now(timezone.utc),
            )
        )
        session.add(
            Controller(
                id=cid,
                name="A",
                base_url="https://x",
                product_kinds="access",
                credentials_blob=cipher.encrypt(b'{"username":"u","password":"p","api_token":null}'),
                verify_tls=False,
                is_default=True,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
        )
        await session.commit()

    fake = FakeAccessController(cid)
    factory = app.state.manager_factory

    class FakeConnection:
        site = "default"

    async def construct(session, controller_id, product, *, site=None):
        return FakeConnection()

    monkeypatch.setattr(factory, "_construct_connection_manager", construct)
    monkeypatch.setattr(
        factory, "_builders_for", lambda product: {"door_manager": lambda cm: fake, "event_manager": lambda cm: fake}
    )
    return app, material.plaintext, cid, fake


def _client(app) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _audit_rows(app) -> list[AuditLog]:
    async with app.state.sessionmaker() as session:
        return list((await session.execute(select(AuditLog))).scalars())


@pytest.fixture(autouse=True)
def _fresh_gates():
    reset_gate_registry_for_tests()
    yield
    configure_gate_settings(GateSettings())
    reset_gate_registry_for_tests()


async def test_concurrent_confirmed_actions_never_overlap_and_run_in_request_order(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())
    headers = {"Authorization": f"Bearer {key}"}
    gate = gate_for(cid, "access")
    fake.hold = asyncio.Event()
    async with _client(app) as client:

        async def lock(door: str):
            return await client.post(
                "/v1/actions/access_lock_door",
                headers=headers,
                json={"site": "default", "controller": cid, "args": {"door_id": door}, "confirm": True},
            )

        # Each request reaches the gate before the next is sent, so "request
        # order" is well defined; the first holds the turn while the rest queue.
        tasks = []
        for i in range(6):
            tasks.append(asyncio.create_task(lock(f"door-{i}")))
            for _ in range(500):
                if gate.write_held and gate.queue_depth == i:
                    break
                await asyncio.sleep(0.001)
        assert gate.queue_depth == 5
        fake.hold.set()
        responses = await asyncio.gather(*tasks)
    assert [response.status_code for response in responses] == [200] * 6
    assert fake.write_overlap is False
    assert fake.writes == [f"door-{i}" for i in range(6)]
    assert gate_for(cid, "access").snapshot()["counters"]["writes_granted"] == 6
    await app.state.engine.dispose()


async def test_a_preview_takes_no_gate(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())
    async with _client(app) as client:
        response = await client.post(
            "/v1/actions/access_lock_door",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"door_id": "d"}, "confirm": False},
        )
    assert response.status_code == 200
    counters = gate_for(cid, "access").snapshot()["counters"]
    assert counters["writes_requested"] == 0 and counters["reads_started"] == 0
    await app.state.engine.dispose()


async def test_a_busy_action_is_refused_with_503_retry_after_and_an_audit_row(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(direct_call_wait_seconds=0.05))
    fake.hold = asyncio.Event()
    headers = {"Authorization": f"Bearer {key}"}
    async with _client(app) as client:

        async def lock(door: str):
            return await client.post(
                "/v1/actions/access_lock_door",
                headers=headers,
                json={"site": "default", "controller": cid, "args": {"door_id": door}, "confirm": True},
            )

        first = asyncio.create_task(lock("held"))
        for _ in range(200):
            if fake.writes:
                break
            await asyncio.sleep(0.001)
        refused = await lock("refused")
        fake.hold.set()
        assert (await first).status_code == 200

    assert refused.status_code == 503
    assert refused.headers["Retry-After"] == "5"
    assert refused.json()["detail"]["kind"] == "controller_busy"
    assert fake.writes == ["held"]
    rows = [row for row in await _audit_rows(app) if row.error_kind == "controller_busy"]
    assert len(rows) == 1 and rows[0].controller == cid and rows[0].target == "access_lock_door"
    await app.state.engine.dispose()


async def test_resource_reads_run_side_by_side_up_to_the_cap_with_one_slot_per_request(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(read_cap=2))
    headers = {"Authorization": f"Bearer {key}"}
    async with _client(app) as client:
        responses = await asyncio.gather(
            *(client.get(f"/v1/sites/default/doors?controller={cid}", headers=headers) for _ in range(5))
        )
    assert [response.status_code for response in responses] == [200] * 5
    assert fake.read_peak == 2
    # The handler's own lookups and its nested read shared the request's one slot.
    assert all(slots <= 2 for slots in fake.nested_slots)
    assert gate_for(cid, "access").snapshot()["counters"]["reads_started"] == 5
    assert gate_for(cid, "access").snapshot()["reads_in_use"] == 0
    await app.state.engine.dispose()


async def test_a_request_never_holds_two_slots_on_one_gate(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(read_cap=1))
    async with _client(app) as client:
        response = await client.get(
            f"/v1/sites/default/doors?controller={cid}", headers={"Authorization": f"Bearer {key}"}
        )
    # With one slot, a second slot for the nested read or the second lookup would deadlock.
    assert response.status_code == 200
    assert fake.nested_slots == [1]
    await app.state.engine.dispose()


async def test_a_busy_resource_read_is_refused_with_503_and_an_audit_row(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(
        tmp_path, monkeypatch, settings=GateSettings(read_cap=1, direct_call_wait_seconds=0.05)
    )
    fake.hold = asyncio.Event()
    headers = {"Authorization": f"Bearer {key}"}
    async with _client(app) as client:
        first = asyncio.create_task(client.get(f"/v1/sites/default/doors?controller={cid}", headers=headers))
        for _ in range(200):
            if fake.reading:
                break
            await asyncio.sleep(0.001)
        refused = await client.get(f"/v1/sites/default/doors?controller={cid}", headers=headers)
        fake.hold.set()
        assert (await first).status_code == 200
    assert refused.status_code == 503
    assert refused.headers["Retry-After"] == "5"
    rows = [row for row in await _audit_rows(app) if row.error_kind == "controller_busy"]
    assert len(rows) == 1
    assert rows[0].controller == cid and rows[0].target == "/sites/{site_id}/doors"
    await app.state.engine.dispose()


async def test_reads_never_wait_behind_a_held_write(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())
    headers = {"Authorization": f"Bearer {key}"}
    release = asyncio.Event()

    async def hold_write() -> None:
        async with gate_for(cid, "access").write(label="holder"):
            await release.wait()

    holder = asyncio.create_task(hold_write())
    await asyncio.sleep(0)
    async with _client(app) as client:
        response = await asyncio.wait_for(
            client.get(f"/v1/sites/default/doors?controller={cid}", headers=headers), timeout=5
        )
    assert response.status_code == 200
    release.set()
    await holder
    await app.state.engine.dispose()


async def test_graphql_reads_take_a_slot_and_report_busy_as_a_code(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(
        tmp_path, monkeypatch, settings=GateSettings(read_cap=1, direct_call_wait_seconds=0.05)
    )
    headers = {"Authorization": f"Bearer {key}"}
    query = {"query": f'{{ access {{ doors(controller: "{cid}") {{ items {{ id }} }} }} }}'}
    async with _client(app) as client:
        ok = await client.post("/v1/graphql", headers=headers, json=query)
        assert ok.status_code == 200 and "errors" not in ok.json(), ok.json()
        assert fake.nested_slots == [1]

        fake.hold = asyncio.Event()
        first = asyncio.create_task(client.post("/v1/graphql", headers=headers, json=query))
        for _ in range(200):
            if fake.reading:
                break
            await asyncio.sleep(0.001)
        busy = await client.post("/v1/graphql", headers=headers, json=query)
        fake.hold.set()
        await first
    error = busy.json()["errors"][0]
    assert error["extensions"] == {"code": "CONTROLLER_BUSY", "retryAfter": 5}
    await app.state.engine.dispose()


def test_gate_settings_come_from_the_api_environment(tmp_path, monkeypatch):
    monkeypatch.setenv("UNIFI_API_GATE_WRITE_HOLD_SECONDS", "300")
    monkeypatch.setenv("UNIFI_API_GATE_CALL_WAIT_SECONDS", "12.5")
    monkeypatch.setenv("UNIFI_API_GATE_READ_CONCURRENCY", "4")
    yaml_path = Path(__file__).resolve().parents[1] / "src" / "unifi_api" / "config.yaml"
    assert load_config(yaml_path).gate == GateConfig(write_hold_seconds=300, call_wait_seconds=12.5, read_concurrency=4)


def test_the_yaml_defaults_match_the_gate_defaults(monkeypatch):
    for name in ("WRITE_HOLD_SECONDS", "CALL_WAIT_SECONDS", "READ_CONCURRENCY"):
        monkeypatch.delenv(f"UNIFI_API_GATE_{name}", raising=False)
    yaml_path = Path(__file__).resolve().parents[1] / "src" / "unifi_api" / "config.yaml"
    assert load_config(yaml_path).gate == GateConfig()


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("write_hold_seconds", "soon"),
        ("write_hold_seconds", 5),
        ("call_wait_seconds", "nan"),
        ("call_wait_seconds", 0),
        ("read_concurrency", "2.5"),
        ("read_concurrency", 65),
        ("read_concurrency", "²"),
        ("read_concurrency", True),
    ],
)
def test_bad_gate_settings_refuse_startup_naming_the_variable(key, value):
    with pytest.raises(ValueError, match=f"UNIFI_API_GATE_{key.upper()}"):
        _gate_config({key: value})


# ---------------------------------------------------------------------------
# Review regressions: request scope lifetime, pool, ids, entry points
# ---------------------------------------------------------------------------


async def _until(predicate, attempts: int = 2000) -> None:
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(0.001)
    raise AssertionError("condition never became true")


async def test_an_orphaned_graphql_field_never_keeps_a_slot_or_reads_after_its_request(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(
        tmp_path, monkeypatch, settings=GateSettings(read_cap=1, direct_call_wait_seconds=5)
    )
    gate = gate_for(cid, "access")
    headers = {"Authorization": f"Bearer {key}"}
    fake.hold = asyncio.Event()
    hold_query = {"query": f'{{ access {{ doors(controller: "{cid}") {{ items {{ id }} }} }} }}'}
    # Field b fails at once (no such controller); its error nulls the parent,
    # which leaves field a still queued for the one slot when the request ends.
    mixed = {
        "query": f'{{ access {{ a: doors(controller: "{cid}") {{ items {{ id }} }} '
        'b: doors(controller: "no-such-controller") { items { id } } } }'
    }
    async with _client(app) as client:
        holder = asyncio.create_task(client.post("/v1/graphql", headers=headers, json=hold_query))
        await _until(lambda: fake.reading == 1)
        answered = await client.post("/v1/graphql", headers=headers, json=mixed)
        assert any(error["extensions"]["code"] == "NOT_FOUND" for error in answered.json()["errors"])
        # The finished request left nothing queued behind it.
        assert gate.snapshot()["reads_waiting"] == 0
        calls_before = len(fake.nested_slots)
        fake.hold.set()
        await holder
        fake.hold = None
        await asyncio.sleep(0.05)
        snapshot = gate.snapshot()
        assert snapshot["reads_in_use"] == 0 and snapshot["reads_waiting"] == 0
        # Field a never read after its request ended.
        assert len(fake.nested_slots) == calls_before
        fresh = await asyncio.wait_for(client.post("/v1/graphql", headers=headers, json=hold_query), 5)
        assert "errors" not in fresh.json(), fresh.json()
    await app.state.engine.dispose()


async def test_a_multi_field_query_with_a_failing_field_releases_every_slot(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(read_cap=1))
    headers = {"Authorization": f"Bearer {key}"}
    fields = " ".join(f'f{i}: doors(controller: "{cid}", limit: {i + 1}) {{ items {{ id }} }}' for i in range(5))
    query = {"query": f'{{ access {{ {fields} bad: doors(controller: "missing") {{ items {{ id }} }} }} }}'}
    async with _client(app) as client:
        answered = await client.post("/v1/graphql", headers=headers, json=query)
        assert answered.json()["errors"]
        ok = await client.post("/v1/graphql", headers=headers, json={"query": f"{{ access {{ {fields} }} }}"})
        assert "errors" not in ok.json(), ok.json()
    snapshot = gate_for(cid, "access").snapshot()
    assert snapshot["reads_in_use"] == 0 and snapshot["reads_waiting"] == 0
    await app.state.engine.dispose()


async def test_a_closed_request_scope_refuses_late_reads_and_cancels_queued_ones():
    configure_gate_settings(GateSettings(read_cap=1))
    gate = gate_for("scope-controller", "access")
    scope = _RequestReadScope()
    blocker_release = asyncio.Event()

    async def blocker() -> None:
        async with gate.read():
            await blocker_release.wait()

    holder = asyncio.create_task(blocker())
    await asyncio.sleep(0)
    late = asyncio.create_task(scope.take(gate, controller_id="scope-controller", label="late"))
    await _until(lambda: gate.snapshot()["reads_waiting"] == 1)
    await scope.release()  # the request ends while the read is still queued
    with pytest.raises(asyncio.CancelledError):
        await late
    with pytest.raises(RequestAlreadyFinished):
        await scope.take(gate, controller_id="scope-controller", label="after")
    blocker_release.set()
    await holder
    assert gate.snapshot()["reads_in_use"] == 0 and gate.snapshot()["reads_waiting"] == 0


async def test_queued_actions_hold_no_database_connection(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(direct_call_wait_seconds=30))
    gate = gate_for(cid, "access")
    fake.hold = asyncio.Event()
    headers = {"Authorization": f"Bearer {key}"}
    async with _client(app) as client:

        async def lock(i: int):
            return await client.post(
                "/v1/actions/access_lock_door",
                headers=headers,
                json={"site": "default", "controller": cid, "args": {"door_id": f"d{i}"}, "confirm": True},
            )

        # More than the database pool holds (5 + 10 overflow).
        tasks = [asyncio.create_task(lock(i)) for i in range(20)]
        await _until(lambda: gate.queue_depth == 19, attempts=5000)
        # Anything that needs the database still gets a connection at once.
        audit = await asyncio.wait_for(_audit_rows(app), 4)
        assert isinstance(audit, list)
        fake.hold.set()
        responses = await asyncio.gather(*tasks)
    assert [response.status_code for response in responses] == [200] * 20
    await app.state.engine.dispose()


async def test_queued_reads_hold_no_database_connection(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(
        tmp_path, monkeypatch, settings=GateSettings(read_cap=1, direct_call_wait_seconds=30)
    )
    gate = gate_for(cid, "access")
    fake.hold = asyncio.Event()
    headers = {"Authorization": f"Bearer {key}"}
    async with _client(app) as client:
        tasks = [
            asyncio.create_task(client.get(f"/v1/sites/default/doors?controller={cid}", headers=headers))
            for _ in range(20)
        ]
        await _until(lambda: gate.snapshot()["reads_waiting"] == 19, attempts=5000)
        audit = await asyncio.wait_for(_audit_rows(app), 4)
        assert isinstance(audit, list)
        fake.hold.set()
        responses = await asyncio.gather(*tasks)
    assert [response.status_code for response in responses] == [200] * 20
    await app.state.engine.dispose()


async def test_unknown_graphql_controller_ids_create_no_gate(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())
    headers = {"Authorization": f"Bearer {key}"}
    before = len(gate_registry().gates())
    async with _client(app) as client:
        for i in range(20):
            query = {"query": f'{{ access {{ doors(controller: "bogus-{i}-{"x" * 64}") {{ items {{ id }} }} }} }}'}
            answered = await client.post("/v1/graphql", headers=headers, json=query)
            assert answered.json()["errors"][0]["extensions"]["code"] == "NOT_FOUND"
    assert len(gate_registry().gates()) == before
    await app.state.engine.dispose()


async def test_an_action_cut_off_by_its_write_budget_reports_an_unknown_outcome(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings(hold_budget_seconds=0.05))
    fake.hang = True
    async with _client(app) as client:
        response = await client.post(
            "/v1/actions/access_lock_door",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"door_id": "d"}, "confirm": True},
        )
    body = response.json()
    assert response.status_code == 200
    assert body["success"] is False and body["mutation_applied"] is None
    assert "may or may not have been applied" in body["error"]
    rows = [row for row in await _audit_rows(app) if row.error_kind == "write_request_timeout"]
    assert len(rows) == 1
    assert not gate_for(cid, "access").write_held
    await app.state.engine.dispose()


async def test_an_action_refused_before_sending_reports_nothing_applied(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())

    class LeapingClock:
        """Each reading is far past the last: the budget is spent before the manager call."""

        def __init__(self) -> None:
            self.value = 0.0

        def now(self) -> float:
            self.value += 1_000.0
            return self.value

        async def sleep(self, seconds: float) -> None:
            await asyncio.sleep(0)

    gate = OperationGate(GateSettings(hold_budget_seconds=120), name="access", clock=LeapingClock())
    gate_registry()._gates[GateKey.for_controller(cid, "access")] = gate
    async with _client(app) as client:
        response = await client.post(
            "/v1/actions/access_lock_door",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": {"door_id": "d"}, "confirm": True},
        )
    body = response.json()
    assert body["success"] is False and body["mutation_applied"] is False
    assert "was not sent" in body["error"]
    assert fake.writes == []
    await app.state.engine.dispose()


@pytest.mark.parametrize(
    "entry", ["get_connection_manager", "get_domain_manager", "get_event_reader", "get_event_reader_cached"]
)
async def test_every_factory_entry_point_takes_the_request_read_slot(tmp_path, monkeypatch, entry):
    app, key, cid, fake = await _bootstrap(
        tmp_path, monkeypatch, settings=GateSettings(read_cap=1, direct_call_wait_seconds=0.05)
    )
    factory = app.state.manager_factory
    gate = gate_for(cid, "access")

    async def reach() -> None:
        async with app.state.sessionmaker() as session:
            if entry == "get_domain_manager":
                await factory.get_domain_manager(session, cid, "access", "door_manager")
            elif entry == "get_event_reader_cached":
                await factory.get_event_reader(session, cid, "access")
            else:
                await getattr(factory, entry)(session, cid, "access")

    # Warm the caches first, so the cached paths are checked too.
    await reach()
    if entry == "get_event_reader_cached":
        # A route built the event manager: get_event_reader returns that cached
        # instance without reaching the connection manager.
        async with app.state.sessionmaker() as session:
            cached = await factory.get_domain_manager(session, cid, "access", "event_manager")
            assert await factory.get_event_reader(session, cid, "access") is cached
    scope = hold_controller_read_slots()
    await scope.__anext__()
    try:
        await reach()
        assert gate.snapshot()["reads_in_use"] == 1
    finally:
        await scope.aclose()
    assert gate.snapshot()["reads_in_use"] == 0

    release = asyncio.Event()

    async def fill_the_slot() -> None:
        async with gate.read():
            await release.wait()

    filler = asyncio.create_task(fill_the_slot())
    await asyncio.sleep(0)
    scope = hold_controller_read_slots()
    await scope.__anext__()
    try:
        with pytest.raises(ControllerBusyError):
            await reach()
    finally:
        await scope.aclose()
        release.set()
        await filler
    await app.state.engine.dispose()


async def test_an_unknown_controller_id_is_refused_before_a_gate_exists(tmp_path, monkeypatch):
    app, key, cid, fake = await _bootstrap(tmp_path, monkeypatch, settings=GateSettings())
    before = len(gate_registry().gates())
    scope = hold_controller_read_slots()
    await scope.__anext__()
    try:
        async with app.state.sessionmaker() as session:
            with pytest.raises(ControllerNotFound):
                await app.state.manager_factory.get_connection_manager(session, "not-a-controller", "access")
    finally:
        await scope.aclose()
    assert len(gate_registry().gates()) == before
    await app.state.engine.dispose()


def _bounded(test, seconds: float = 20.0):
    """Fail a hung test instead of letting it hang the suite."""
    import functools

    @functools.wraps(test)
    async def bounded(*args, **kwargs):
        return await asyncio.wait_for(test(*args, **kwargs), seconds)

    return bounded


for _name, _test in list(globals().items()):
    if _name.startswith("test_") and asyncio.iscoroutinefunction(_test):
        globals()[_name] = _bounded(_test)
