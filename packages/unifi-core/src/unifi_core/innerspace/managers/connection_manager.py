"""Session client for UniFi InnerSpace on a UniFi OS console.

InnerSpace is read with the console session only: a login on ``/api/auth/login``
returns the ``TOKEN`` cookie and a CSRF token, and both go on every request,
including the logout. There is no API-key path.

Rules the rest of the package relies on:

* The destination is the configured console (``https://{host}:{port}``). Every
  request path must be root-relative and stay on that origin; redirects are
  never followed and proxy settings from the environment are ignored, so the
  session cookie cannot be sent anywhere else.
* The cookie jar is not used. The session cookie is taken from a successful
  login only and sent as an explicit header, so a cookie set by any other
  response is never stored or replayed.
* Error text is fixed: the operation, the HTTP status and an ``errors.*``
  code matching a fixed pattern. Never the response body, the console address, the request
  path or an exception's text, and errors are raised outside ``except`` blocks
  so nothing is chained. Logs carry the operation, a route template and the
  exception class.
* A refused session (401, or 403 ``errors.api.access``, which the console
  returns for a missing or expired cookie and for an account without access)
  is re-established once under a lock and the request retried once, except for
  a write sent with ``replay=False``: the session is re-established and
  :class:`InnerSpaceWriteNotSent` raised, so a write reaches the console at
  most once, and a write the console did not answer raises
  :class:`InnerSpaceWriteOutcomeUnknown` (see ``_writes``). A refusal
  of the fresh session is a permission error, and for a short window after it
  further refusals raise the same error without another login; for a write,
  "fresh" means the session issued after the previous write was refused. A
  write refused by UniFi OS itself (403 without an ``errors.*`` code) renews
  the session without sending the write again, and the read-back decides. A rejected
  login drops the session and pauses automatic reconnects on an escalating
  cool-down, so repeated calls cannot lock the account out.
* Inside a held write of the operation gate, every request except the login
  and logout is bounded by what is left of the write's hold budget
  (:func:`~unifi_core.operation_gate.write_request_bound`). A write the budget
  stopped before it was sent raises :class:`InnerSpaceWriteOutOfTime`; one cut
  off after it was sent is a write the console did not answer.
* ``/api/system`` answers a missing or expired session with 200 and a public
  payload that has no application list, so on that route a 2xx without
  ``apps.controllers`` is a refused session too, and its CSRF token is never
  adopted. If the session issued for the retry still gets no list, the account
  cannot read the app list: a permission error, and for a short window further
  list-less replies raise it without another login.
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import ipaddress
import json as _json
import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Collection, Mapping, TypeVar

import aiohttp
from yarl import URL

from unifi_core.auth import AuthenticationStatus
from unifi_core.connect_attempt import ConnectAttempt
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiError,
    UniFiMalformedResponseError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.innerspace.models.status import app_status_from_api
from unifi_core.operation_gate import WriteRequestTimeout, write_request_bound
from unifi_core.tls import (
    CertificateVerificationError,
    certificate_error_hint,
    certificate_safe_middleware,
    is_certificate_error,
    ssl_setting,
    warn_if_unverified,
)

logger = logging.getLogger(__name__)

INTEGRATION_PREFIX = "/proxy/innerspace/integration/v1"
LOGIN_PATH = "/api/auth/login"
LOGOUT_PATH = "/api/auth/logout"
SYSTEM_PATH = "/api/system"
INTERNAL_PREFIX = "/proxy/innerspace/api"
INTERNAL_PROJECT_PATH = f"{INTERNAL_PREFIX}/project"
# Internal write routes; AGENTS.md lists them and bans any other.
SHAPE_CHANGE_PATH = f"{INTERNAL_PREFIX}/shape/change"
WALL_TYPE_PATH = f"{INTERNAL_PROJECT_PATH}/wall-type"
ATTENUATION_OBJECT_TYPE_PATH = f"{INTERNAL_PROJECT_PATH}/attenuation-object-type"
PLAN_PATH_PREFIX = f"{INTERNAL_PROJECT_PATH}/plan"
PLAN_ORDER_PATH = f"{PLAN_PATH_PREFIX}/order"

_REQUEST_TIMEOUT_SECONDS = 30.0
_CONNECT_ATTEMPT_TIMEOUT_SECONDS = 15.0
# Automatic reconnects make at most one attempt per interval.
_RECONNECT_MIN_INTERVAL_SECONDS = 30.0
# A rejected login blocks automatic reconnects for the base interval, doubling
# per consecutive rejection up to the cap, then allows one attempt.
_RECONNECT_BLOCK_BASE_SECONDS = 60.0
_RECONNECT_BLOCK_MAX_SECONDS = 900.0
_APP_STATUS_CACHE_SECONDS = 30.0
# After the console refuses a session issued for the same call, refusals within
# this window raise the permission error without logging in again.
_NO_ACCESS_WINDOW_SECONDS = 60.0
# Bodies are read up to a cap and never beyond it: JSON replies here, binary
# replies at the caller's cap, which cannot exceed the asset ceiling.
_JSON_CEILING_BYTES = 32_000_000
ASSET_CEILING_BYTES = 16_000_000
_READ_CHUNK_BYTES = 65_536
_IMAGE_MAGIC = {"image/png": b"\x89PNG\r\n\x1a\n", "image/jpeg": b"\xff\xd8\xff"}

_SESSION_REFUSED_CODE = "errors.api.access"
_ERROR_CODE = re.compile(r"errors\.[A-Za-z.]{1,64}")
# Root-relative paths of unreserved characters only: no empty, dot or
# percent-encoded segments, no query, fragment, userinfo or backslash.
_SAFE_PATH = re.compile(r"(?:/[A-Za-z0-9._~:-]+)+")

# Which call may send a route: the session code (login, logout), ``request`` (JSON) or
# ``request_bytes`` (the plan image).
_SESSION, _JSON, _BYTES = "session", "json", "bytes"

# Every route the session may reach, with the methods allowed on it and the call that may send
# it; anything else is refused before sending. Literal routes are matched exactly. The order route
# comes before the plan template, which would also match it.
_LOG_ROUTES = tuple(
    (re.compile(pattern), template, frozenset(methods), entry)
    for pattern, template, methods, entry in (
        *(
            (re.escape(path), path, methods, entry)
            for path, methods, entry in (
                (LOGIN_PATH, {"POST"}, _SESSION),
                (LOGOUT_PATH, {"POST"}, _SESSION),
                (SYSTEM_PATH, {"GET"}, _JSON),
                (INTERNAL_PROJECT_PATH, {"GET", "PATCH"}, _JSON),
                (SHAPE_CHANGE_PATH, {"POST"}, _JSON),
                (WALL_TYPE_PATH, {"POST"}, _JSON),
                (ATTENUATION_OBJECT_TYPE_PATH, {"POST"}, _JSON),
                (PLAN_ORDER_PATH, {"PATCH"}, _JSON),
                *(
                    (f"{INTEGRATION_PREFIX}/{name}", {"GET"}, _JSON)
                    for name in ("project", "floor_plans", "access_points", "switches", "inventory")
                ),
            )
        ),
        # Never the reorder segment, in any case: that route takes a different body.
        (
            re.escape(f"{PLAN_PATH_PREFIX}/") + rf"(?!(?i:{re.escape(PLAN_ORDER_PATH.rpartition('/')[2])})$)[^/]+",
            f"{PLAN_PATH_PREFIX}/{{plan_id}}",
            {"PATCH"},
            _JSON,
        ),
        (
            re.escape(f"{INTEGRATION_PREFIX}/assets/") + r"[^/]+/[^/]+",
            f"{INTEGRATION_PREFIX}/assets/{{folder}}/{{file}}",
            {"GET"},
            _BYTES,
        ),
    )
)

_NOT_CONFIGURED = "The UniFi OS console host, username and password must all be configured for InnerSpace."
_REJECTED = (
    "The UniFi OS console rejected the configured username and password. Check them; "
    "automatic reconnects back off after each rejection."
)
# Login answers that mean the console refused these credentials.
_CREDENTIAL_REFUSED_STATUSES = frozenset({400, 401, 403})
_LOGIN_ROUTE_REFUSED = (
    "The UniFi OS console's login route answered HTTP %s. Check that the configured host and port point at a "
    "UniFi OS console; automatic reconnects back off after each refusal."
)
_RATE_LIMITED = "The UniFi OS console rate-limited the login. Automatic reconnects back off after each refusal."
_NO_SESSION_ISSUED = (
    "The UniFi OS console accepted the login request but issued no session. Automatic reconnects back off "
    "after each refusal."
)
_SESSION_REJECTED = "The UniFi OS console refused the session right after a fresh login."
_UNREACHABLE = (
    "Could not log in to the UniFi OS console. Check that the configured host and port are reachable from "
    "this machine and that they point at the console."
)
_UNEXPECTED = "Could not log in to the UniFi OS console because of an unexpected client error."
_NOT_CONNECTED = "Not connected to the UniFi OS console."
_PERMISSION = (
    "the console refused the session for InnerSpace (expired session or an account without InnerSpace access). "
    "Reads need a UniFi OS account that can open the InnerSpace application, e.g. a Super Admin."
)
_ACCOUNT_CANNOT_WRITE = (
    "the console account cannot make this change: the console refused the write on a session it had just issued"
)
_CANNOT_WRITE = f"{_ACCOUNT_CANNOT_WRITE}, so it was not sent again and nothing was changed"
_NO_APP_LIST = (
    "the console account cannot read the application list: the console answered without it on a session it "
    "had just issued. Reads need a UniFi OS account that can open the InnerSpace application, e.g. a Super Admin."
)


_UNKNOWN_ROUTE = "/{unknown}"


def _match_route(path: str) -> tuple[str, frozenset[str], str | None]:
    route = path.partition("?")[0].partition("#")[0]
    for pattern, template, methods, entry in _LOG_ROUTES:
        if pattern.fullmatch(route):
            return template, methods, entry
    return _UNKNOWN_ROUTE, frozenset(), None


def _log_route(path: str) -> str:
    """Return fixed route vocabulary only, including for unknown paths and queries."""
    return _match_route(path)[0]


def _is_loopback(host: str) -> bool:
    if host.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(host.strip("[]")).is_loopback
    except ValueError:
        return False


def _console_origin(host: str, port: int, base_url: str | None) -> URL:
    """The one origin requests go to. ``base_url`` is for tests: https, or http on loopback only."""
    error: str | None = None
    try:
        if base_url is None:
            return URL.build(scheme="https", host=host, port=port)
        url = URL(base_url)
    except (TypeError, ValueError):
        error = "InnerSpace console address is not a valid host and port"
    else:
        if (
            url.scheme not in ("http", "https")
            or not url.host
            or url.user is not None
            or url.password is not None
            or url.path not in ("", "/")
            or url.query_string
            or url.fragment
        ):
            error = "InnerSpace base_url must be a bare http(s) origin"
        elif url.scheme == "http" and not _is_loopback(url.host):
            error = "InnerSpace base_url must use https unless it is a loopback address"
        else:
            return url.origin()
    raise ValueError(error)


class InnerSpaceUnavailableError(UniFiConnectionError):
    """InnerSpace cannot serve the operation: no session, or the app is not running."""


class InnerSpaceHttpError(UniFiOperationError):
    """The console answered with a status this client does not map to a narrower error."""

    def __init__(self, message: str, *, status: int, code: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code


class InnerSpaceWriteNotSent(UniFiOperationError):
    """The console refused the session before acting on a write; it was not sent again."""


class InnerSpaceWriteOutOfTime(UniFiOperationError):
    """The write's hold budget ran out before the write was sent; it was not sent."""


class InnerSpaceWriteForbidden(UniFiPermissionError):
    """UniFi OS refused a sent write on a session it had just issued; only a read can tell what changed."""


class InnerSpaceWriteOutcomeUnknown(UniFiConnectionError):
    """A write was sent and no answer came back (timeout or dropped connection); only a read can tell."""


class _SessionRejectedError(UniFiAuthError):
    """The console refused a session it had just issued."""


class _LoginRouteRefusedError(UniFiAuthError):
    """The login route refused the request with a status that does not mean bad credentials."""

    def __init__(self, message: str, *, status: int) -> None:
        super().__init__(message)
        self.status = status


class _NoSessionIssuedError(UniFiAuthError):
    """The console answered the login with success but without a session cookie and CSRF token."""


@dataclass(frozen=True, slots=True)
class _SessionAuth:
    """The session cookie and CSRF token from one login. Never rendered."""

    token: str = field(repr=False)
    csrf: str = field(repr=False)

    def headers(self) -> dict[str, str]:
        return {"Cookie": f"TOKEN={self.token}", "X-CSRF-Token": self.csrf}


@dataclass(frozen=True, slots=True)
class _Reply:
    status: int
    payload: Any = None
    is_json: bool = False
    body: bytes = b""
    content_type: str | None = None
    oversize: bool = False
    token: str | None = field(default=None, repr=False)
    csrf: str | None = field(default=None, repr=False)


async def _read_capped(response: aiohttp.ClientResponse, limit: int) -> tuple[bytes, bool]:
    """Read the decoded body up to ``limit`` bytes; ``True`` when it is longer (the rest stays unread)."""
    declared = response.content_length
    # Refuse on the declared length alone: it fails closed, since nothing is read and the
    # caller treats the reply as oversize whatever the body would have held.
    if declared is not None and declared > limit:
        return b"", True
    chunks: list[bytes] = []
    total = 0
    async for chunk in response.content.iter_chunked(_READ_CHUNK_BYTES):
        total += len(chunk)
        if total > limit:
            return b"", True
        chunks.append(chunk)
    return b"".join(chunks), False


def _error_code(payload: Any) -> str | None:
    """The console's ``error.code`` when it is an ``errors.*`` code matching a fixed pattern."""
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


def _session_refused(reply: _Reply, path: str | None = None) -> bool:
    """401, 403 ``errors.api.access``, or (for ``path`` ``/api/system``) a 2xx JSON reply without the app list."""
    if reply.status == 401 or (reply.status == 403 and _error_code(reply.payload) == _SESSION_REFUSED_CODE):
        return True
    return path == SYSTEM_PATH and _without_app_list(reply)


def _has_app_list(payload: Any) -> bool:
    """Whether a ``/api/system`` payload carries ``apps.controllers`` as a list; only a session it accepts gets it."""
    apps = payload.get("apps") if isinstance(payload, dict) else None
    return isinstance(apps, dict) and isinstance(apps.get("controllers"), list)


def _without_app_list(reply: _Reply) -> bool:
    """A 2xx JSON reply without the app list: the public ``/api/system`` payload served to a refused session."""
    return 200 <= reply.status < 300 and reply.is_json and not _has_app_list(reply.payload)


class InnerSpaceConnectionManager:
    """Holds one UniFi OS console session for InnerSpace reads.

    Parameters
    ----------
    host, port:
        The UniFi OS console. Requests go to ``https://{host}:{port}`` only. An
        empty host means "not configured": the manager is built, makes no request
        and every operation raises the fixed unavailable error.
    username, password:
        A local console account with access to InnerSpace.
    verify_ssl, ssl_fingerprint:
        Certificate checks; a fingerprint pins the certificate and wins over
        ``verify_ssl``. See :mod:`unifi_core.tls`.
    tls_env_prefix:
        Server prefix naming the settings that TLS errors and the unverified-TLS
        warning point at, e.g. ``"INNERSPACE"``. Leave unset for a consumer that
        does not read those variables; nothing is warned then.
    base_url:
        Test-only replacement origin. Must be https, or http on a loopback address.
    auth_failure_hint:
        Fixed text appended to the connection failure when no credentials are
        configured or the console rejected the login, and to no other failure. It
        is shown to callers verbatim and never logged, so it must not carry a secret.
    """

    # How a write's read-back waits between reads; ``readback_sleep=`` replaces it per manager.
    readback_sleep: Callable[[float], Awaitable[Any]] = staticmethod(asyncio.sleep)

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
        ssl_fingerprint: str | None = None,
        tls_env_prefix: str | None = None,
        *,
        base_url: str | None = None,
        auth_failure_hint: str | None = None,
        readback_sleep: Callable[[float], Awaitable[Any]] | None = None,
    ) -> None:
        host = host.strip() if isinstance(host, str) else host
        self.host = host
        self.port = port
        self.tls_env_prefix = tls_env_prefix
        self.auth_failure_hint = auth_failure_hint
        self._username = username
        self._password = password
        # A malformed pin or address fails here, not on the first request.
        self._tls = ssl_setting(verify_ssl, ssl_fingerprint)
        self._origin = _console_origin(host, port, base_url) if (host.strip() or base_url) else None
        self._timeout = aiohttp.ClientTimeout(total=_REQUEST_TIMEOUT_SECONDS)
        self._clock: Callable[[], float] = time.monotonic

        self._session: aiohttp.ClientSession | None = None
        self._auth: _SessionAuth | None = None
        self._auth_lock = asyncio.Lock()
        if readback_sleep is not None:
            self.readback_sleep = readback_sleep
        self._attempt = ConnectAttempt()

        self._closed = False
        self._initialize_attempted = False
        self._tls_warned = False
        self._last_connection_error: str | None = None
        self._last_attempt_at: float | None = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0
        self._app_running_until = 0.0
        self._no_access_until = 0.0
        # Until then, a list-less /api/system reply raises the permission error without another login.
        self._app_list_refused_until = 0.0
        # The session issued after a write was refused; a write refused on it too is a permission error.
        self._write_refused_token: str | None = None

    # ------------------------------------------------------------------
    # Status
    # ------------------------------------------------------------------

    @property
    def is_connected(self) -> bool:
        return not self._closed and self._session is not None and self._auth is not None

    @property
    def authentication_status(self) -> AuthenticationStatus:
        return AuthenticationStatus(
            session_configured=self._credentials_configured(),
            api_key_configured=False,
            session_available=self.is_connected,
            api_key_available=None,
        )

    @property
    def last_connection_error(self) -> str | None:
        """Why the last connection attempt failed (fixed text), or ``None`` after a success."""
        return self._last_connection_error

    @property
    def connect_in_progress(self) -> bool:
        """Whether a connection attempt, at start-up or automatic, is running."""
        return self._attempt.in_progress

    @property
    def reconnect_due(self) -> bool:
        """Whether an automatic reconnect attempt would run now.

        Only a manager whose owner has called :meth:`initialize` reconnects.
        """
        if not self._initialize_attempted or self._closed or self.is_connected:
            return False
        if not self._credentials_configured() or self._reconnect_block_remaining() > 0:
            return False
        if self._last_attempt_at is None:
            return True
        return self._clock() - self._last_attempt_at >= _RECONNECT_MIN_INTERVAL_SECONDS

    @property
    def reconnect_blocked(self) -> bool:
        """Whether the console refused the last login and none has succeeded since.

        It stays set when the cool-down runs out, so a caller that has proved the
        login works again (the API's probe) can drop this cached manager instead of
        waiting the cool-down out.
        """
        return self._reconnect_block_count > 0

    def _credentials_configured(self) -> bool:
        return self._origin is not None and bool(self._username and self._password)

    def _reconnect_block_remaining(self) -> float:
        return max(0.0, self._reconnect_block_until - self._clock())

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Log in once. Returns ``False`` and sets :attr:`last_connection_error` on failure.

        Runs as the manager's one connection attempt, so a server can call it
        in the background while operations wait on it within a bound.
        """
        self._closed = False
        self._initialize_attempted = True
        if self.tls_env_prefix and not self._tls_warned:
            self._tls_warned = True
            warn_if_unverified(logger, self._tls, product="InnerSpace", env_prefix=self.tls_env_prefix)
        if self.is_connected:
            return True
        if self._attempt.in_progress:
            return await self._attempt.join()
        self._attempt.start(self._connect_attempt, name="innerspace-connect")
        return await self._attempt.join()

    async def reconnect(self) -> bool:
        """Make one automatic reconnect attempt when one is due; ``True`` when connected afterwards."""
        if not self._attempt.in_progress:
            if not self.reconnect_due:
                return self.is_connected
            self._attempt.start(self._reconnect_once, name="innerspace-reconnect")
        await self._attempt.wait()
        return self.is_connected

    async def _reconnect_once(self) -> bool:
        if not self.reconnect_due:
            return self.is_connected
        logger.info("[innerspace-cm] Attempting automatic reconnect to the UniFi OS console")
        return await self._connect_attempt()

    async def _connect_attempt(self) -> bool:
        if not self._credentials_configured():
            self._last_connection_error = self._with_auth_failure_hint(_NOT_CONFIGURED)
            return False
        try:
            await self._connect_once()
        except Exception as exc:
            self._record_connect_failure(exc)
            return False
        finally:
            self._last_attempt_at = self._clock()
        self._last_connection_error = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0
        logger.info("[innerspace-cm] Logged in to the UniFi OS console")
        return True

    async def _connect_once(self) -> None:
        await self._discard_session()
        session = self._new_session()
        try:
            async with asyncio.timeout(_CONNECT_ATTEMPT_TIMEOUT_SECONDS):
                async with self._auth_lock:
                    auth = await self._login(session)
        except BaseException:
            await session.close()
            raise
        self._session, self._auth = session, auth

    def _record_connect_failure(self, error: BaseException) -> None:
        # Fixed text by class: never the exception's own text.
        if isinstance(error, _SessionRejectedError):
            text = _SESSION_REJECTED
        elif isinstance(error, _NoSessionIssuedError):
            text = _NO_SESSION_ISSUED
        elif isinstance(error, _LoginRouteRefusedError):
            text = _LOGIN_ROUTE_REFUSED % error.status
        elif isinstance(error, UniFiAuthError):
            text = self._with_auth_failure_hint(_REJECTED)
        elif isinstance(error, UniFiRateLimitError):
            text = _RATE_LIMITED
        elif is_certificate_error(error):
            text = certificate_error_hint(env_prefix=self.tls_env_prefix)
        elif isinstance(error, (UniFiConnectionError, TimeoutError)):
            text = _UNREACHABLE
        else:
            text = _UNEXPECTED
        self._last_connection_error = text
        logger.error("[innerspace-cm] Could not log in to the UniFi OS console: %s", type(error).__name__)
        if isinstance(error, (UniFiAuthError, UniFiRateLimitError)):
            self._block_automatic_reconnect()

    def _with_auth_failure_hint(self, message: str) -> str:
        """``message`` followed by the configured hint for a credential failure, if any."""
        return f"{message} {self.auth_failure_hint}" if self.auth_failure_hint else message

    def _block_automatic_reconnect(self) -> None:
        self._reconnect_block_count += 1
        cooldown = min(
            _RECONNECT_BLOCK_BASE_SECONDS * (2 ** (self._reconnect_block_count - 1)),
            _RECONNECT_BLOCK_MAX_SECONDS,
        )
        self._reconnect_block_until = self._clock() + cooldown
        logger.error(
            "[innerspace-cm] Automatic reconnect blocked after the console refused the login; "
            "the next attempt is allowed in %.0f seconds.",
            cooldown,
        )

    def _unavailable(self, operation: str) -> InnerSpaceUnavailableError:
        if self._attempt.in_progress:
            return InnerSpaceUnavailableError(
                f"{operation}: still connecting to the UniFi OS console. The attempt continues in the background "
                "and a later call uses the connection once it succeeds."
            )
        text = f"{operation}: {self._last_connection_error or (_NOT_CONNECTED if self._origin else _NOT_CONFIGURED)}"
        if self._reconnect_block_remaining() > 0:
            text += " Automatic reconnect is paused after the refused login."
        return InnerSpaceUnavailableError(text)

    async def close(self) -> None:
        """Log out when a session exists, close the HTTP session and stop reconnects. Idempotent.

        Waits for a re-login in progress, so the session it creates is the one logged out.
        """
        self._closed = True
        await self._attempt.cancel()
        async with self._auth_lock:
            await self._discard_session(logout=True)

    async def _discard_session(self, *, logout: bool = False) -> None:
        session, auth = self._session, self._auth
        self._session, self._auth = None, None
        self._app_running_until = 0.0
        if session is None:
            return
        if logout and auth is not None:
            await self._logout(session, auth, level=logging.WARNING)
        await session.close()

    async def _logout(self, session: aiohttp.ClientSession, auth: _SessionAuth, *, level: int) -> None:
        """End ``auth`` on the console; a failure is logged at ``level`` by class or status only."""
        try:
            reply = await self._send(
                session, "POST", LOGOUT_PATH, operation="InnerSpace logout", headers=auth.headers(), entry=_SESSION
            )
        except UniFiError as exc:
            logger.log(level, "[innerspace-cm] Logout failed: %s", type(exc).__name__)
        else:
            if reply.status != 200:
                logger.log(level, "[innerspace-cm] Logout answered HTTP %s", reply.status)

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _session_middlewares(self) -> tuple[aiohttp.ClientMiddlewareType, ...]:
        """Replace a failed certificate check with fixed text before anything else sees it."""
        return (certificate_safe_middleware(env_prefix=self.tls_env_prefix),)

    def _new_session(self) -> aiohttp.ClientSession:
        return aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self._tls),
            cookie_jar=aiohttp.DummyCookieJar(),
            middlewares=self._session_middlewares(),
            timeout=self._timeout,
            trust_env=False,
        )

    def _url(self, method: str, path: str, operation: str, entry: str) -> URL:
        """Join ``path`` to the console origin, refusing any path that could leave it or re-target it.

        Only the routes in ``_LOG_ROUTES`` are sent, with the methods listed for each and only from
        the call (``entry``) that owns them: the console session can reach every console API, so the
        client itself is the boundary that keeps it on InnerSpace.
        """
        _template, methods, owner = _match_route(path) if isinstance(path, str) else ("", frozenset(), None)
        if self._origin is not None and (
            isinstance(path, str)
            and _SAFE_PATH.fullmatch(path)
            and not any(segment in (".", "..") for segment in path.split("/"))
            and method in methods
            and entry == owner
        ):
            url = self._origin.with_path(path, encoded=True)
            if url.origin() == self._origin:
                return url
        raise UniFiValidationError(f"{operation}: refused an unsafe InnerSpace request path")

    async def _send(
        self,
        session: aiohttp.ClientSession,
        method: str,
        path: str,
        *,
        operation: str,
        headers: dict[str, str],
        entry: str = _JSON,
        params: Mapping[str, str] | None = None,
        json_body: Any = None,
        limit: int | None = None,
        binary: bool = False,
    ) -> _Reply:
        """Send one request, never following a redirect, and read the answer up to ``limit`` bytes.

        The URL is built here from ``method``, ``path`` and ``entry`` (:meth:`_url`), so the method the
        allowlist checked is the method sent. A longer body sets ``oversize`` and the rest is not read.
        With ``binary`` a 2xx body is returned as bytes instead of being parsed as JSON. ``limit``
        defaults to the JSON ceiling.
        """
        url = self._url(method, path, operation, entry)
        if params:
            url = url.with_query(dict(params))
        limit = _JSON_CEILING_BYTES if limit is None else limit
        failure: UniFiConnectionError | None = None
        cause = ""
        try:
            async with session.request(
                method,
                url,
                headers={"Accept": "image/png, image/jpeg" if binary else "application/json", **headers},
                json=json_body,
                allow_redirects=False,
            ) as response:
                status = response.status
                body, oversize = await _read_capped(response, limit)
                content_type = response.headers.get("Content-Type", "").partition(";")[0].strip().lower() or None
                token = response.cookies.get("TOKEN")
                csrf = response.headers.get("X-Updated-Csrf-Token") or response.headers.get("X-Csrf-Token")
        except CertificateVerificationError as exc:
            cause = type(exc).__name__
            # Fixed text by construction (unifi_core.tls); rebuilt so it carries the operation and no chain.
            failure = CertificateVerificationError(f"{operation}: {exc}")
        except TimeoutError as exc:
            cause = type(exc).__name__
            failure = UniFiConnectionError(f"{operation}: the UniFi OS console did not answer in time")
        except aiohttp.ClientError as exc:
            cause = type(exc).__name__
            failure = UniFiConnectionError(
                f"{operation}: the request to the UniFi OS console failed ({type(exc).__name__})"
            )
        if failure is not None:
            logger.warning("[innerspace-cm] %s: %s %s failed (%s)", operation, method, _log_route(path), cause)
            raise failure
        logger.debug("[innerspace-cm] %s %s answered HTTP %s", method, _log_route(path), status)
        token_value = token.value if token else None
        if binary and 200 <= status < 300:
            return _Reply(status, body=body, content_type=content_type, oversize=oversize, token=token_value, csrf=csrf)
        try:
            if oversize:
                raise ValueError
            payload, is_json = _json.loads(body), True
        except ValueError:
            payload, is_json = None, False
        return _Reply(status, payload, is_json, oversize=oversize, token=token_value, csrf=csrf)

    async def _login(self, session: aiohttp.ClientSession) -> _SessionAuth:
        """Log in on ``session`` and return the new session cookie and CSRF token. Caller holds the lock."""
        operation = "InnerSpace console login"
        reply = await self._send(
            session,
            "POST",
            LOGIN_PATH,
            operation=operation,
            headers={},
            entry=_SESSION,
            json_body={"username": self._username, "password": self._password},
        )
        if reply.status == 200 and reply.token and reply.csrf:
            return _SessionAuth(token=reply.token, csrf=reply.csrf)
        if reply.status == 429:
            raise UniFiRateLimitError(_RATE_LIMITED)
        # Every other refusal of the request, and a success without a session, takes the cool-down.
        # Only a credential refusal names the credentials (and carries the auth-failure hint).
        if reply.status in _CREDENTIAL_REFUSED_STATUSES:
            raise UniFiAuthError(_REJECTED)
        if 400 <= reply.status < 500:
            raise _LoginRouteRefusedError(_LOGIN_ROUTE_REFUSED % reply.status, status=reply.status)
        if 200 <= reply.status < 300:
            raise _NoSessionIssuedError(_NO_SESSION_ISSUED)
        raise UniFiConnectionError(f"{operation}: the console answered HTTP {reply.status} without a session")

    async def _relogin(self, refused: _SessionAuth, operation: str) -> None:
        """Replace a refused session once, however many callers saw it refused.

        Only the first caller under the lock logs in; the others find a
        different session token in place and retry with it. Sessions are told
        apart by token only, so a CSRF token rotated meanwhile does not count. The replaced session is
        logged out, since the console also refuses a session that is still
        valid but lacks access. A failed login drops the session for every
        caller and, when the console rejected it, opens the cool-down.
        """
        async with self._auth_lock:
            session = self._session
            if not self.is_connected or session is None:
                error = self._unavailable(operation)
            elif self._auth is None or self._auth.token != refused.token:
                return
            else:
                replaced = self._auth
                logger.info("[innerspace-cm] %s: session refused; logging in again", operation)
                failure: Exception | None = None
                try:
                    self._auth = await self._login(session)
                except UniFiError as exc:
                    failure = exc
                if failure is None:
                    # Expected to be refused when the old session had expired.
                    await self._logout(session, replaced, level=logging.DEBUG)
                    return
                await self._drop_session(failure)
                error = self._unavailable(operation)
        raise error

    async def _reject_session(self, refused: _SessionAuth, operation: str) -> None:
        """A session issued moments ago was refused again: drop it and stop."""
        async with self._auth_lock:
            if self._auth is not None and self._auth.token == refused.token:
                await self._drop_session(_SessionRejectedError(_SESSION_REJECTED))
        raise self._unavailable(operation)

    async def _drop_session(self, failure: Exception) -> None:
        await self._discard_session()
        self._last_attempt_at = self._clock()
        self._record_connect_failure(failure)

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------

    async def request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        replay: bool = True,
    ) -> Any:
        """Send one request with the session and return the decoded JSON body.

        A refused session is re-established once and the request retried once.
        With ``replay=False`` (writes) the request is never sent twice: a refused
        session is re-established and :class:`InnerSpaceWriteNotSent` raised, and
        a timeout or connection failure after sending raises
        :class:`InnerSpaceWriteOutcomeUnknown`. Every failure raises a typed error
        with fixed text naming ``operation``.
        """
        reply = await self._exchange(method, path, operation=operation, params=params, json=json, replay=replay)
        return self._interpret(reply, operation)

    async def request_bytes(
        self,
        path: str,
        *,
        operation: str,
        max_bytes: int,
        allowed_types: Collection[str],
    ) -> tuple[bytes, str]:
        """GET a PNG or JPEG and return its bytes and content type.

        At most ``max_bytes`` (never more than :data:`ASSET_CEILING_BYTES`) are read; a longer
        body, a content type outside ``allowed_types`` or bytes that are not the image type
        they claim to be raise a typed error with fixed text. Redirects are never followed.
        """
        limit = min(max_bytes, ASSET_CEILING_BYTES)
        reply = await self._exchange("GET", path, operation=operation, limit=limit, binary=True)
        self._check_status(reply, operation)
        if reply.oversize:
            raise UniFiMalformedResponseError(f"{operation}: the image is larger than the allowed size")
        content_type = reply.content_type
        magic = _IMAGE_MAGIC.get(content_type or "")
        if content_type not in allowed_types or magic is None or not reply.body.startswith(magic):
            raise UniFiMalformedResponseError(
                f"{operation}: the console returned something other than an allowed image"
            )
        return reply.body, content_type

    async def _exchange(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        params: Mapping[str, str] | None = None,
        json: Any = None,
        limit: int | None = None,
        binary: bool = False,
        replay: bool = True,
    ) -> _Reply:
        """Send with the session; on a refused session log in once and send once more (reads only)."""
        if self._origin is None:
            raise self._unavailable(operation)
        entry = _BYTES if binary else _JSON
        # Refused here too, before the session checks, so a refused route never depends on them.
        self._url(method, path, operation, entry)
        auth, session = self._auth, self._session
        if auth is None or session is None or self._closed:
            raise self._unavailable(operation)
        send = functools.partial(
            self._send,
            method=method,
            path=path,
            operation=operation,
            entry=entry,
            params=params,
            json_body=json,
            limit=limit,
            binary=binary,
        )
        sent = False

        async def send_bounded(session: aiohttp.ClientSession, auth: _SessionAuth) -> _Reply:
            # Bounded inside a held write by what is left of its hold budget; outside one, unbounded.
            # The login and logout of the session code never pass through here.
            nonlocal sent
            async with write_request_bound():
                sent = True
                return await send(session, headers=auth.headers())

        unanswered = out_of_time = False
        try:
            reply = await send_bounded(session, auth)
        except CertificateVerificationError:
            # The handshake failed, so nothing was sent.
            raise
        except WriteRequestTimeout:
            # Fixed text from the gate; a read keeps it as it is, so its guidance reaches the caller.
            if replay:
                raise
            out_of_time, unanswered = not sent, sent
        except UniFiConnectionError:
            if replay:
                raise
            unanswered = True
        if out_of_time:
            raise InnerSpaceWriteOutOfTime(
                f"{operation}: the write's time budget ran out before it was sent, so nothing was changed"
            )
        if unanswered:
            raise InnerSpaceWriteOutcomeUnknown(
                f"{operation}: the UniFi OS console did not answer the write, so whether it was applied is unknown"
            )
        if not _session_refused(reply, path):
            if not replay:
                await self._after_unrefused_write(reply, auth, operation)
            self._note_app_list(reply, path)
            return self._adopt_csrf(reply, auth)
        if not replay and self._second_write_refusal(auth):
            # A second refusal in a row: the account can read but not write. Stop instead of logging in again.
            raise UniFiPermissionError(f"{operation}: {_CANNOT_WRITE}")
        if reply.status == 403 and self._clock() < self._no_access_until:
            raise UniFiPermissionError(f"{operation}: {_PERMISSION}")
        if path == SYSTEM_PATH and _without_app_list(reply) and self._clock() < self._app_list_refused_until:
            raise UniFiPermissionError(f"{operation}: {_NO_APP_LIST}")

        await self._relogin(auth, operation)
        if not replay:
            self._write_refused_token = self._auth.token if self._auth is not None else None
            raise InnerSpaceWriteNotSent(
                f"{operation}: the console refused the session before acting on the write; the session was "
                "renewed and the write was not sent again, so nothing was changed"
            )
        auth, session = self._auth, self._session
        if auth is None or session is None or self._closed:
            raise self._unavailable(operation)
        reply = await send_bounded(session, auth)
        if reply.status == 401:
            await self._reject_session(auth, operation)
        if _session_refused(reply):
            self._no_access_until = self._clock() + _NO_ACCESS_WINDOW_SECONDS
            raise UniFiPermissionError(f"{operation}: {_PERMISSION}")
        if path == SYSTEM_PATH and _without_app_list(reply):
            self._app_list_refused_until = self._clock() + _NO_ACCESS_WINDOW_SECONDS
            raise UniFiPermissionError(f"{operation}: {_NO_APP_LIST}")
        self._no_access_until = 0.0
        self._note_app_list(reply, path)
        return self._adopt_csrf(reply, auth)

    def _note_app_list(self, reply: _Reply, path: str) -> None:
        """A 2xx ``/api/system`` reply that carries the list shows the account can read it: close the window."""
        if path == SYSTEM_PATH and 200 <= reply.status < 300 and _has_app_list(reply.payload):
            self._app_list_refused_until = 0.0

    async def _after_unrefused_write(self, reply: _Reply, auth: _SessionAuth, operation: str) -> None:
        """A write the session check let through. A 403 without an ``errors.*`` code is UniFi OS refusing it
        (e.g. a stale CSRF token): the session is renewed now, for the read-back and the next call, and the
        write is not sent again. A failed renewal drops the session; the read-back then fails. The same refusal
        on the renewed session (or inside the no-access window) is a permission error, without another login."""
        if reply.status != 403 or _error_code(reply.payload) is not None:
            self._write_refused_token = None
            return
        if self._second_write_refusal(auth):
            # The write reached UniFi OS, so this does not claim what changed: the read-back decides.
            raise InnerSpaceWriteForbidden(f"{operation}: {_ACCOUNT_CANNOT_WRITE} (HTTP 403)")
        try:
            await self._relogin(auth, operation)
        except UniFiError:
            logger.info("[innerspace-cm] %s: session renewal after a refused write failed", operation)
        self._write_refused_token = self._auth.token if self._auth is not None else None

    def _second_write_refusal(self, auth: _SessionAuth) -> bool:
        """Whether this write refusal follows one on the session just issued (or falls in the no-access window).

        If so, the account can read but not write: the window opens and no further login is tried.
        """
        if self._clock() < self._no_access_until or auth.token == self._write_refused_token:
            self._write_refused_token = None
            self._no_access_until = self._clock() + _NO_ACCESS_WINDOW_SECONDS
            return True
        return False

    def _adopt_csrf(self, reply: _Reply, auth: _SessionAuth) -> _Reply:
        """Keep a CSRF token the console rotated on a successful reply to the current session.

        A reply that also sets a session cookie replaces both together; a cookie
        without a CSRF token changes nothing.
        """
        current = self._auth
        if not 200 <= reply.status < 300 or not reply.csrf or current is None or current.token != auth.token:
            return reply
        rotated = _SessionAuth(token=reply.token or current.token, csrf=reply.csrf)
        if rotated != current:
            self._auth = rotated
        return reply

    def _interpret(self, reply: _Reply, operation: str) -> Any:
        self._check_status(reply, operation)
        if reply.oversize:
            raise UniFiMalformedResponseError(
                f"{operation}: the console returned a response larger than the allowed size"
            )
        if not reply.is_json:
            raise UniFiMalformedResponseError(f"{operation}: the console returned a response that is not JSON")
        return reply.payload

    def _check_status(self, reply: _Reply, operation: str) -> None:
        """Raise the typed error for any status outside 2xx.

        A 404 is an :class:`InnerSpaceHttpError`, not "not found": the console
        answers it for a route it does not serve, which says nothing about the
        object asked for. Any HTTP error also drops the cached app status, so
        the next read checks the app again.
        """
        status = reply.status
        if 200 <= status < 300:
            return
        self._app_running_until = 0.0
        if 300 <= status < 400:
            raise InnerSpaceHttpError(
                f"{operation}: the console answered with an unexpected redirect (HTTP {status}); not followed",
                status=status,
            )
        if status == 429:
            raise UniFiRateLimitError(f"{operation}: the console rate-limited the request (HTTP 429)")
        code = _error_code(reply.payload)
        suffix = f" ({code})" if code else ""
        raise InnerSpaceHttpError(f"{operation}: the console answered HTTP {status}{suffix}", status=status, code=code)

    async def ensure_app_running(self, operation: str) -> None:
        """Raise unless ``/api/system`` reports InnerSpace running. A running result is cached briefly."""
        if self._clock() < self._app_running_until:
            return
        status = app_status_from_api(await self.request("GET", SYSTEM_PATH, operation=operation))
        if not status.installed:
            raise InnerSpaceUnavailableError(f"{operation}: InnerSpace is not installed on this console")
        if not status.running:
            raise InnerSpaceUnavailableError(f"{operation}: InnerSpace is not running on this console")
        self._app_running_until = self._clock() + _APP_STATUS_CACHE_SECONDS


_ManagerT = TypeVar("_ManagerT", bound=type)


def reconnects_on_demand(cls: _ManagerT) -> _ManagerT:
    """Give an InnerSpace manager one automatic reconnect attempt per operation.

    Every public coroutine method first asks ``self._cm`` to reconnect when it
    has no session and an attempt is due, or waits on an attempt already
    running within that attempt's bound. The attempt runs before the operation
    sends anything, so no request is ever replayed.
    """
    for name, member in list(vars(cls).items()):
        if name.startswith("_") or not inspect.iscoroutinefunction(member):
            continue
        setattr(cls, name, _with_reconnect(member))
    return cls


def _with_reconnect(method: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
    @functools.wraps(method)
    async def wrapper(self: Any, *args: Any, **kwargs: Any) -> Any:
        cm = getattr(self, "_cm", None)
        # ``is True`` keeps test doubles, whose attributes are mocks, inert.
        if getattr(cm, "reconnect_due", None) is True or getattr(cm, "connect_in_progress", None) is True:
            await cm.reconnect()
        return await method(self, *args, **kwargs)

    return wrapper
