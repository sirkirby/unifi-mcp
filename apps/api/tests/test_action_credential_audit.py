"""Audit ``detail`` must not carry submitted credential values.

Runs the action route against the real ``SystemManager`` + ``ConnectionManager``
with a fake aiounifi controller that fails while quoting the submitted secret,
then reads the audit row back and asserts the sentinel is absent from the
response body, the captured log and the audit detail.
"""

import codecs
import json
import logging
from unittest.mock import AsyncMock, MagicMock
from urllib.parse import quote

import pytest
from aiounifi.errors import ResponseError
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from unifi_api.db.models import AuditLog
from unifi_core.network.managers.connection_manager import ConnectionManager
from unifi_core.network.managers.system_manager import SystemManager

from tests.test_action_endpoint import _bootstrap

SENTINEL = "SENTINEL-community-secret-c0de"
LOGIN_SENTINEL = "SENTINEL-login-secret-5a5a"
INT_SENTINEL = 987654321987


class _Session:
    closed = False

    async def close(self):
        return None


class _Config:
    def __init__(self):
        self.session = _Session()


class _Connectivity:
    def __init__(self):
        self.can_retry_login = True
        self.config = _Config()
        self.is_unifi_os = True


class _Controller:
    def __init__(self, *, fail_reads: bool):
        self.connectivity = _Connectivity()
        self._fail_reads = fail_reads

    async def login(self):
        self.connectivity.can_retry_login = False

    async def request(self, api_request):
        if api_request.method == "get":
            if self._fail_reads:
                raise ResponseError(f"auth failed for admin:{LOGIN_SENTINEL}")
            return {"data": [{"_id": "snmp-1", "key": "snmp", "enabled": False}]}
        raise ResponseError(f"controller rejected {api_request.data!r}")


def _real_system_manager(*, fail_reads: bool = False) -> SystemManager:
    controller = _Controller(fail_reads=fail_reads)
    connection = ConnectionManager("192.168.1.1", "admin", LOGIN_SENTINEL)
    connection.controller = controller
    connection._aiohttp_session = controller.connectivity.config.session
    connection._initialized = True
    connection._auth_generation = 1
    return SystemManager(connection)


async def _app_with_manager(tmp_path, monkeypatch, caplog, manager):
    monkeypatch.setenv("UNIFI_API_DB_KEY", "k")
    app, key, cid = await _bootstrap(tmp_path)
    factory = MagicMock()
    factory.get_domain_manager = AsyncMock(return_value=manager)
    app.state.manager_factory = factory
    caplog.set_level(logging.DEBUG)
    return app, key, cid, factory


async def _audit_rows(app, tool_name):
    async with app.state.sessionmaker() as session:
        rows = (await session.execute(select(AuditLog))).scalars().all()
    return [row for row in rows if row.target == tool_name]


async def _post(app, key, cid, tool_name, args, confirm):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        return await client.post(
            f"/v1/actions/{tool_name}",
            headers={"Authorization": f"Bearer {key}"},
            json={"site": "default", "controller": cid, "args": args, "confirm": confirm},
        )


@pytest.mark.asyncio
async def test_write_error_audit_detail_is_scrubbed(tmp_path, monkeypatch, caplog) -> None:
    manager = _real_system_manager()
    app, key, cid, _ = await _app_with_manager(tmp_path, monkeypatch, caplog, manager)

    response = await _post(app, key, cid, "unifi_update_snmp_settings", {"enabled": True, "community": SENTINEL}, True)

    assert response.status_code == 200
    assert SENTINEL not in response.text
    assert SENTINEL not in caplog.text
    rows = await _audit_rows(app, "unifi_update_snmp_settings")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert rows[0].error_kind == "ResponseError"
    assert SENTINEL not in (rows[0].detail or "")
    await manager._connection.cleanup()


@pytest.mark.asyncio
async def test_read_error_audit_detail_is_scrubbed(tmp_path, monkeypatch, caplog) -> None:
    manager = _real_system_manager(fail_reads=True)
    app, key, cid, _ = await _app_with_manager(tmp_path, monkeypatch, caplog, manager)

    response = await _post(app, key, cid, "unifi_get_snmp_settings", {}, False)

    assert response.status_code == 200
    assert LOGIN_SENTINEL not in response.text
    assert LOGIN_SENTINEL not in caplog.text
    rows = await _audit_rows(app, "unifi_get_snmp_settings")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert LOGIN_SENTINEL not in (rows[0].detail or "")
    await manager._connection.cleanup()


@pytest.mark.asyncio
async def test_preview_validation_error_audit_detail_is_scrubbed(tmp_path, monkeypatch, caplog) -> None:
    """Schema validation echoes the offending value; a secret-keyed value must still be scrubbed."""
    app, key, cid, factory = await _app_with_manager(tmp_path, monkeypatch, caplog, None)

    response = await _post(
        app, key, cid, "unifi_update_snmp_settings", {"enabled": True, "community": INT_SENTINEL}, False
    )

    assert response.status_code == 200
    assert str(INT_SENTINEL) not in response.text
    factory.get_domain_manager.assert_not_awaited()
    rows = await _audit_rows(app, "unifi_update_snmp_settings")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert rows[0].detail, "audit detail should still explain the validation failure"
    assert str(INT_SENTINEL) not in rows[0].detail


# ---------------------------------------------------------------------------
# Encoded representations
#
# Schema validation quotes the offending value with ``repr``. A credential
# holding a backslash, quote or newline never appears literally in that
# message, so a literal-only scrub persists a fully decodable copy in the
# audit row. No controller or manager is involved in this path.
#
# The oracle below is a copy of packages/unifi-core/tests/secret_assertions.py
# — the two packages have no shared test-helper path, and it must stay in step
# with that file, which is the source of truth. Hand-written on purpose: an
# oracle built from the production enumeration cannot catch a missing form.
# ---------------------------------------------------------------------------

# A credential holding a backslash, a quote, a newline and a non-ASCII
# character: no emitter renders all four the same way, which is what makes a
# whole-string enumeration look like it worked.
ESCAPED_SENTINEL = 'SENTINEL\\backslash"quote\nnewline-pä-e5c1'


def _sentinel_encodings(secret: str) -> dict[str, str]:
    """Every rendering of ``secret`` a message on these paths can carry."""
    return {
        "literal": secret,
        "repr": repr(secret)[1:-1],
        "ascii": ascii(secret)[1:-1],
        # json.dumps escapes quotes and backslashes either way; ensure_ascii
        # decides only whether non-ASCII becomes \uXXXX or stays literal. Node,
        # Jackson and orjson all emit the second form on the wire.
        "json_ascii": json.dumps(secret)[1:-1],
        "json_unicode": json.dumps(secret, ensure_ascii=False)[1:-1],
        # aiounifi renders the raw body with repr(bytes) on its 429 path, which
        # escapes non-ASCII as UTF-8 byte escapes.
        "bytes_repr": repr(secret.encode())[2:-1],
        # A URL carries it percent-encoded, and ClientResponseError prints the
        # URL it failed on.
        "percent": quote(secret, safe=""),
    }


def _assert_unrecoverable(text: str, secret: str) -> None:
    """The secret must not survive literally or in any form we can decode."""
    for name, form in _sentinel_encodings(secret).items():
        assert form not in text, f"secret recoverable from its {name} form"
    # Best-effort, never swallowed: a partially scrubbed secret is exactly what
    # leaves a dangling escape behind, so a decode failure must not silently
    # turn into a pass. This leg only catches ASCII escapes — ``unicode_escape``
    # reads the UTF-8 bytes of a non-ASCII character as latin-1 — so the
    # enumerated forms above are what cover a non-ASCII secret.
    decoded = codecs.decode(text.encode("utf-8", "surrogatepass"), "unicode_escape", errors="replace")
    assert secret not in decoded


@pytest.mark.asyncio
async def test_validation_error_audit_detail_hides_escaped_credential(tmp_path, monkeypatch, caplog) -> None:
    app, key, cid, factory = await _app_with_manager(tmp_path, monkeypatch, caplog, None)

    response = await _post(
        app, key, cid, "unifi_update_snmp_settings", {"enabled": True, "community": [ESCAPED_SENTINEL]}, False
    )

    assert response.status_code == 200
    factory.get_domain_manager.assert_not_awaited()
    _assert_unrecoverable(response.text, ESCAPED_SENTINEL)
    _assert_unrecoverable(caplog.text, ESCAPED_SENTINEL)
    rows = await _audit_rows(app, "unifi_update_snmp_settings")
    assert len(rows) == 1
    assert rows[0].outcome == "error"
    assert rows[0].detail, "audit detail should still explain the validation failure"
    _assert_unrecoverable(rows[0].detail, ESCAPED_SENTINEL)


@pytest.mark.asyncio
async def test_write_error_audit_detail_hides_escaped_credential(tmp_path, monkeypatch, caplog) -> None:
    manager = _real_system_manager()
    app, key, cid, _ = await _app_with_manager(tmp_path, monkeypatch, caplog, manager)

    response = await _post(
        app, key, cid, "unifi_update_snmp_settings", {"enabled": True, "community": ESCAPED_SENTINEL}, True
    )

    assert response.status_code == 200
    _assert_unrecoverable(response.text, ESCAPED_SENTINEL)
    _assert_unrecoverable(caplog.text, ESCAPED_SENTINEL)
    rows = await _audit_rows(app, "unifi_update_snmp_settings")
    assert len(rows) == 1
    _assert_unrecoverable(rows[0].detail or "", ESCAPED_SENTINEL)
    await manager._connection.cleanup()


@pytest.mark.asyncio
async def test_validation_error_audit_detail_omits_any_submitted_value(tmp_path, monkeypatch, caplog) -> None:
    """A credential can arrive under a key the secret vocabulary does not know.

    The audit row is durable and readable by every key holder, so it must not
    echo a submitted value at all — only the field and the failure.
    """
    app, key, cid, factory = await _app_with_manager(tmp_path, monkeypatch, caplog, None)
    operator_value = "pw-under-an-unknown-key-9b21"

    response = await _post(
        app, key, cid, "unifi_update_snmp_settings", {"enabled": [operator_value], "community": "c"}, False
    )

    assert response.status_code == 200
    factory.get_domain_manager.assert_not_awaited()
    rows = await _audit_rows(app, "unifi_update_snmp_settings")
    assert len(rows) == 1
    assert rows[0].detail, "audit detail should still explain the validation failure"
    assert operator_value not in rows[0].detail
    assert "enabled" in rows[0].detail, "the failing field must still be named"


def test_validation_message_never_quotes_the_submitted_value() -> None:
    """The value must not enter the message at all: every sink downstream of
    ``_validate_action_args`` (audit row, HTTP body, log) then has nothing to
    subtract."""
    from types import SimpleNamespace

    from unifi_api.services.actions import _validate_action_args

    entry = SimpleNamespace(
        name="unifi_update_snmp_settings",
        input_schema={"type": "object", "properties": {"community": {"type": "string"}}},
    )

    with pytest.raises(ValueError) as excinfo:
        _validate_action_args(entry, {"community": [ESCAPED_SENTINEL]})

    message = str(excinfo.value)
    assert "args.community" in message, "the failing field must still be named"
    assert "string" in message, "the constraint must still be named"
    _assert_unrecoverable(message, ESCAPED_SENTINEL)


def test_validation_message_names_the_unknown_argument() -> None:
    """Every catalog action sets ``additionalProperties: false``, so a typo'd
    argument name is the most common failure. The name is a caller's key, not a
    caller's value, and the MCP side already echoes it."""
    from types import SimpleNamespace

    from unifi_api.services.actions import _validate_action_args

    entry = SimpleNamespace(
        name="unifi_update_snmp_settings",
        input_schema={
            "type": "object",
            "properties": {"community": {"type": "string"}},
            "additionalProperties": False,
        },
    )

    with pytest.raises(ValueError) as excinfo:
        _validate_action_args(entry, {"communtiy": "c"})

    assert "communtiy" in str(excinfo.value)


def test_validation_message_names_the_missing_argument() -> None:
    """``required`` carries no path, so it sorts first and is often the only
    diagnostic the caller gets. The missing names come from the schema."""
    from types import SimpleNamespace

    from unifi_api.services.actions import _validate_action_args

    entry = SimpleNamespace(
        name="unifi_create_acl_rule",
        input_schema={
            "type": "object",
            "properties": {"name": {"type": "string"}, "network_id": {"type": "string"}},
            "required": ["name", "network_id"],
        },
    )

    with pytest.raises(ValueError) as excinfo:
        _validate_action_args(entry, {"name": "n"})

    message = str(excinfo.value)
    assert "network_id" in message
    assert "name" not in message.split("missing argument(s)")[-1]


def test_translator_validation_error_carries_no_submitted_value() -> None:
    """~20 translators build pydantic models from caller data and only one
    catches ValidationError; the rest reach the audit row as ``str(e)``, which
    embeds ``input_value=`` — truncated at ~50 characters, so a long credential
    survives in fragments no value-matching scrub can find."""
    from pydantic import BaseModel, ValidationError
    from unifi_api.services.actions import _value_free_validation_error

    class _Credential(BaseModel):
        token: str

    with pytest.raises(ValidationError) as excinfo:
        _Credential(token=[ESCAPED_SENTINEL * 3])

    message = str(_value_free_validation_error("access_create_credential", excinfo.value))
    assert "token" in message, "the failing field must still be named"
    assert "access_create_credential" in message
    _assert_unrecoverable(message, ESCAPED_SENTINEL)


def test_audit_detail_scrubs_a_submitted_value_from_any_error() -> None:
    """``_audit_detail`` is the last barrier for a message built outside the two
    paths that now keep values out of their own text — a serializer or a
    translator raising from somewhere else. Without this the barrier can be
    deleted with a green suite."""
    from unifi_api.routes.actions import _audit_detail
    from unifi_api.serializers._base import SerializerContractError

    error = SerializerContractError(f"contract broken while rendering {ESCAPED_SENTINEL!r}")

    detail = _audit_detail(error, {"enabled": True, "community": ESCAPED_SENTINEL})

    assert "contract broken" in detail, "the failure must still be named"
    _assert_unrecoverable(detail, ESCAPED_SENTINEL)
