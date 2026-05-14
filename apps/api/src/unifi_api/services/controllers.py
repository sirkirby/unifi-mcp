"""Controller CRUD service. Encryption uses ColumnCipher on credentials_blob."""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

import aiohttp
from sqlalchemy import select
from sqlalchemy import update as sa_update
from sqlalchemy.ext.asyncio import AsyncSession

from unifi_api.db.crypto import ColumnCipher
from unifi_api.db.models import Controller

KNOWN_QUIRKS_BY_PRODUCT = {
    "protect": ["ptz_zoom_misclass"],
    "access": ["credentials_404"],
}


class ControllerNotFound(Exception):
    pass


@dataclass(frozen=True)
class CreateControllerPayload:
    name: str
    base_url: str
    username: str
    password: str
    api_token: str | None
    product_kinds: list[str]
    verify_tls: bool
    is_default: bool


def _serialize_creds(p: CreateControllerPayload) -> bytes:
    return json.dumps(
        {
            "username": p.username,
            "password": p.password,
            "api_token": p.api_token,
        }
    ).encode("utf-8")


async def _clear_default_flag(session: AsyncSession) -> None:
    await session.execute(sa_update(Controller).values(is_default=False))


async def create_controller(
    session: AsyncSession,
    cipher: ColumnCipher,
    payload: CreateControllerPayload,
) -> Controller:
    if payload.is_default:
        await _clear_default_flag(session)
    now = datetime.now(timezone.utc)
    row = Controller(
        id=str(uuid.uuid4()),
        name=payload.name,
        base_url=payload.base_url,
        product_kinds=",".join(payload.product_kinds),
        credentials_blob=cipher.encrypt(_serialize_creds(payload)),
        verify_tls=payload.verify_tls,
        is_default=payload.is_default,
        created_at=now,
        updated_at=now,
    )
    session.add(row)
    await session.flush()
    return row


async def list_controllers(session: AsyncSession) -> list[Controller]:
    result = await session.execute(select(Controller).order_by(Controller.created_at))
    return list(result.scalars().all())


async def get_controller(session: AsyncSession, controller_id: str) -> Controller:
    row = (await session.execute(select(Controller).where(Controller.id == controller_id))).scalar_one_or_none()
    if row is None:
        raise ControllerNotFound(controller_id)
    return row


async def update_controller(
    session: AsyncSession,
    cipher: ColumnCipher,
    controller_id: str,
    *,
    name: str | None = None,
    base_url: str | None = None,
    product_kinds: list[str] | None = None,
    verify_tls: bool | None = None,
    is_default: bool | None = None,
    username: str | None = None,
    password: str | None = None,
    api_token: str | None = None,
) -> Controller:
    row = await get_controller(session, controller_id)
    if name is not None:
        row.name = name
    if base_url is not None:
        row.base_url = base_url
    if product_kinds is not None:
        row.product_kinds = ",".join(product_kinds)
    if verify_tls is not None:
        row.verify_tls = verify_tls
    if is_default is True:
        await _clear_default_flag(session)
        row.is_default = True
    elif is_default is False:
        row.is_default = False
    creds_changed = any(v is not None for v in (username, password, api_token))
    if creds_changed:
        existing = json.loads(cipher.decrypt(row.credentials_blob))
        if username is not None:
            existing["username"] = username
        if password is not None:
            existing["password"] = password
        if api_token is not None:
            existing["api_token"] = api_token
        row.credentials_blob = cipher.encrypt(json.dumps(existing).encode("utf-8"))
    row.updated_at = datetime.now(timezone.utc)
    await session.flush()
    return row


async def delete_controller(session: AsyncSession, controller_id: str) -> None:
    row = await get_controller(session, controller_id)
    await session.delete(row)
    await session.flush()


async def probe_capabilities(controller: Controller) -> dict:
    """Probe a controller for product presence + version + V2 API support.

    Best-effort: timeouts and per-step exceptions are caught and converted
    to a probe_error field. Always returns the full payload shape.
    """
    payload: dict = {
        "id": controller.id,
        "name": controller.name,
        "base_url": controller.base_url,
        "products": [],
        "version": {"controller": None, "firmware": None},
        "v2_api": False,
        "sites": [],
        "known_quirks": [],
        "probed_at": datetime.now(timezone.utc).isoformat(),
        "probe_error": None,
    }
    declared = [p for p in controller.product_kinds.split(",") if p]

    timeout = aiohttp.ClientTimeout(total=5)
    connector = aiohttp.TCPConnector(ssl=controller.verify_tls)
    try:
        async with aiohttp.ClientSession(timeout=timeout, connector=connector) as session:
            try:
                async with session.get(f"{controller.base_url}/api/system") as r:
                    if r.status == 200:
                        body = await r.json(content_type=None)
                        payload["version"]["controller"] = body.get("version") or body.get("data", {}).get("version")
            except Exception as e:
                payload["probe_error"] = f"system probe failed: {e}"

            for product in ("network", "protect", "access"):
                if product not in declared:
                    continue
                probe_path = {
                    "network": "/proxy/network/api/s/default/stat/sysinfo",
                    "protect": "/proxy/protect/api/cameras",
                    "access": "/proxy/access/api/v1/developer/devices",
                }[product]
                try:
                    async with session.get(f"{controller.base_url}{probe_path}") as r:
                        if r.status < 500:
                            payload["products"].append(product)
                            payload["known_quirks"].extend(KNOWN_QUIRKS_BY_PRODUCT.get(product, []))
                            if product == "network":
                                text = await r.text()
                                if "v2" in text.lower():
                                    payload["v2_api"] = True
                except Exception as e:
                    if payload["probe_error"] is None:
                        payload["probe_error"] = f"{product} probe failed: {e}"
    except Exception as e:
        payload["probe_error"] = f"probe session failed: {e}"

    return payload
