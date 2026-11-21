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
from unifi_api.services.operation_gate import configure_gate_settings, gate_for
from unifi_core.operation_gate import GateSettings, reset_gate_registry_for_tests


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

    async def apply_lock_door(self, door_id: str) -> dict:
        self.writing += 1
        self.write_overlap |= self.writing > 1
        self.writes.append(door_id)
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
    monkeypatch.setattr(factory, "_builders_for", lambda product: {"door_manager": lambda cm: fake})
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
