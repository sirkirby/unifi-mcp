"""Bearer token auth middleware as a FastAPI dependency factory.

`_authenticate` resolves a bearer token to an ApiKey row (or raises 401).
`require_scope(scope)` returns a FastAPI dependency that authenticates and
then enforces the requested scope (raises 403 on insufficient scope).
"""

from __future__ import annotations

import time
from typing import Callable

from fastapi import HTTPException, Request, status
from sqlalchemy import select

from unifi_api.auth.api_key import KEY_PATTERN, KEY_PREFIX_LEN, verify_key
from unifi_api.auth.cache import ArgonVerifyCache, CachedKey
from unifi_api.auth.scopes import Scope, parse_scopes, scope_allows
from unifi_api.db.models import ApiKey
from unifi_api.logging import key_id_prefix_ctx
from unifi_api.services.audit import write_audit


async def _audit_denial(app, *, key_id_prefix: str, target: str, error_kind: str) -> None:
    """Best-effort denial audit. Uses a fresh session so middleware doesn't depend on caller transaction state."""
    sm = app.state.sessionmaker
    async with sm() as session:
        await write_audit(
            session,
            key_id_prefix=key_id_prefix,
            controller=None,
            target=target,
            outcome="denied",
            error_kind=error_kind,
        )
        await session.commit()


async def _authenticate(request: Request) -> ApiKey:
    target = f"{request.method} {request.url.path}"
    auth_header = request.headers.get("authorization", "")
    if not auth_header.lower().startswith("bearer "):
        await _audit_denial(request.app, key_id_prefix="(none)", target=target, error_kind="missing_bearer")
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="missing bearer token")
    plaintext = auth_header[len("Bearer ") :].strip()

    if not KEY_PATTERN.fullmatch(plaintext):
        await _audit_denial(
            request.app,
            key_id_prefix=plaintext[:KEY_PREFIX_LEN] or "(short)",
            target=target,
            error_kind="malformed_token",
        )
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="malformed token")

    cache: ArgonVerifyCache = request.app.state.argon_cache
    cached = cache.get(plaintext)
    sm = request.app.state.sessionmaker

    if cached is not None:
        # Cache hit — confirm not revoked
        async with sm() as session:
            row = (await session.execute(select(ApiKey).where(ApiKey.id == cached.api_key_id))).scalar_one_or_none()
            if row is None or row.revoked_at is not None:
                cache.invalidate(cached.api_key_id)
                await _audit_denial(
                    request.app, key_id_prefix=plaintext[:KEY_PREFIX_LEN], target=target, error_kind="unknown_token"
                )
                raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown token")
            key_id_prefix_ctx.set(row.prefix)
            request.state.api_key_prefix = row.prefix
            return row

    # Cache miss — full argon2 verify path
    prefix = plaintext[:KEY_PREFIX_LEN]
    async with sm() as session:
        row = (await session.execute(select(ApiKey).where(ApiKey.prefix == prefix))).scalar_one_or_none()
        if row is None or row.revoked_at is not None:
            await _audit_denial(request.app, key_id_prefix=prefix, target=target, error_kind="unknown_token")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="unknown token")
        if not verify_key(plaintext, row.hash):
            await _audit_denial(request.app, key_id_prefix=prefix, target=target, error_kind="invalid_token")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid token")

    cache.put(plaintext, CachedKey(api_key_id=row.id, scopes=row.scopes, fetched_at=time.time()))
    key_id_prefix_ctx.set(row.prefix)
    request.state.api_key_prefix = row.prefix
    return row


def require_scope(required: Scope) -> Callable:
    async def _dep(request: Request) -> ApiKey:
        api_key = await _authenticate(request)
        held = parse_scopes(api_key.scopes)
        if not scope_allows(held, required):
            await _audit_denial(
                request.app,
                key_id_prefix=api_key.prefix,
                target=f"{request.method} {request.url.path}",
                error_kind="insufficient_scope",
            )
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="insufficient scope")
        return api_key

    return _dep
