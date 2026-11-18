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
* Error text is fixed: the operation, the HTTP status and an allowlisted
  ``errors.*`` code. Never the response body, the console address, the request
  path or an exception's text, and errors are raised outside ``except`` blocks
  so nothing is chained. Logs carry the operation, a route template and the
  exception class.
* A refused session (401, or 403 ``errors.api.access``, which the console
  returns for a missing or expired cookie) is re-established once under a lock
  and the request retried once. A rejected login drops the session and pauses
  automatic reconnects on an escalating cool-down, so repeated calls cannot
  lock the account out.
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
from typing import Any, Awaitable, Callable, Mapping, TypeVar

import aiohttp
from yarl import URL

from unifi_core.auth import AuthenticationStatus
from unifi_core.connect_attempt import ConnectAttempt
from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiError,
    UniFiMalformedResponseError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.innerspace.models.status import app_status_from_api
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
INTERNAL_PROJECT_PATH = "/proxy/innerspace/api/project"

_REQUEST_TIMEOUT_SECONDS = 30.0
_CONNECT_ATTEMPT_TIMEOUT_SECONDS = 15.0
# Automatic reconnects make at most one attempt per interval.
_RECONNECT_MIN_INTERVAL_SECONDS = 30.0
# A rejected login blocks automatic reconnects for the base interval, doubling
# per consecutive rejection up to the cap, then allows one attempt.
_RECONNECT_BLOCK_BASE_SECONDS = 60.0
_RECONNECT_BLOCK_MAX_SECONDS = 900.0
_APP_STATUS_CACHE_SECONDS = 30.0

_SESSION_REFUSED_CODE = "errors.api.access"
_ERROR_CODE = re.compile(r"errors\.[A-Za-z.]{1,64}")
# Root-relative paths of unreserved characters only: no empty, dot or
# percent-encoded segments, no query, fragment, userinfo or backslash.
_SAFE_PATH = re.compile(r"(?:/[A-Za-z0-9._~:-]+)+")

_LOG_ROUTES = tuple(
    (re.compile(pattern), template)
    for pattern, template in (
        (re.escape(LOGIN_PATH), LOGIN_PATH),
        (re.escape(LOGOUT_PATH), LOGOUT_PATH),
        (re.escape(SYSTEM_PATH), SYSTEM_PATH),
        (re.escape(INTERNAL_PROJECT_PATH), INTERNAL_PROJECT_PATH),
        *(
            (re.escape(f"{INTEGRATION_PREFIX}/{name}"), f"{INTEGRATION_PREFIX}/{name}")
            for name in ("project", "floor_plans", "access_points", "switches", "inventory")
        ),
        (
            re.escape(f"{INTEGRATION_PREFIX}/assets/") + r"[^/]+/[^/]+",
            f"{INTEGRATION_PREFIX}/assets/{{folder}}/{{file}}",
        ),
    )
)

_NOT_CONFIGURED = "The UniFi OS console host, username and password must all be configured for InnerSpace."
_REJECTED = (
    "The UniFi OS console rejected the configured username and password. Check them; "
    "automatic reconnects back off after each rejection."
)
_RATE_LIMITED = "The UniFi OS console rate-limited the login. Automatic reconnects back off after each refusal."
_SESSION_REJECTED = "The UniFi OS console refused the session right after a fresh login."
_UNREACHABLE = (
    "Could not log in to the UniFi OS console. Check that the configured host and port are reachable from "
    "this machine and that they point at the console."
)
_NOT_CONNECTED = "Not connected to the UniFi OS console."
_PERMISSION = (
    "the console refused the session for InnerSpace (expired session or an account without InnerSpace access). "
    "Reads need a UniFi OS account that can open the InnerSpace application; they were tested with a Super Admin."
)


def _log_route(path: str) -> str:
    """Return fixed route vocabulary only, including for unknown paths and queries."""
    route = path.partition("?")[0].partition("#")[0]
    for pattern, template in _LOG_ROUTES:
        if pattern.fullmatch(route):
            return template
    return "/{unknown}"


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


class _SessionRejectedError(UniFiAuthError):
    """The console refused a session it had just issued."""


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
    token: str | None = field(default=None, repr=False)
    csrf: str | None = field(default=None, repr=False)


def _error_code(payload: Any) -> str | None:
    """The console's ``error.code`` when it is an allowlisted ``errors.*`` code."""
    error = payload.get("error") if isinstance(payload, dict) else None
    code = error.get("code") if isinstance(error, dict) else None
    return code if isinstance(code, str) and _ERROR_CODE.fullmatch(code) else None


def _session_refused(reply: _Reply) -> bool:
    return reply.status == 401 or (reply.status == 403 and _error_code(reply.payload) == _SESSION_REFUSED_CODE)


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
    ) -> None:
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
        self._attempt = ConnectAttempt()

        self._closed = False
        self._initialize_attempted = False
        self._tls_warned = False
        self._last_connection_error: str | None = None
        self._last_attempt_at: float | None = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0
        self._reconnect_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._app_running_until = 0.0

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
        if self._attempt.in_progress and await self._attempt.join():
            return True
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

    def add_reconnect_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Run ``callback`` after each successful automatic reconnect."""
        self._reconnect_callbacks.append(callback)

    async def _reconnect_once(self) -> bool:
        if not self.reconnect_due:
            return self.is_connected
        logger.info("[innerspace-cm] Attempting automatic reconnect to the UniFi OS console")
        if not await self._connect_attempt():
            return False
        for callback in list(self._reconnect_callbacks):
            try:
                await callback()
            except Exception as exc:
                logger.error("[innerspace-cm] Reconnect callback failed: %s", type(exc).__name__)
        return True

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
        elif isinstance(error, UniFiAuthError):
            text = self._with_auth_failure_hint(_REJECTED)
        elif isinstance(error, UniFiRateLimitError):
            text = _RATE_LIMITED
        elif is_certificate_error(error):
            text = certificate_error_hint(env_prefix=self.tls_env_prefix)
        else:
            text = _UNREACHABLE
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
        """Log out when a session exists, close the HTTP session and stop reconnects. Idempotent."""
        self._closed = True
        await self._attempt.cancel()
        await self._discard_session(logout=True)

    async def _discard_session(self, *, logout: bool = False) -> None:
        session, auth = self._session, self._auth
        self._session, self._auth = None, None
        self._app_running_until = 0.0
        if session is None:
            return
        if logout and auth is not None:
            try:
                reply = await self._send(
                    session,
                    "POST",
                    LOGOUT_PATH,
                    self._url(LOGOUT_PATH, "InnerSpace logout"),
                    operation="InnerSpace logout",
                    headers=auth.headers(),
                )
            except UniFiError as exc:
                logger.debug("[innerspace-cm] Logout failed: %s", type(exc).__name__)
            else:
                if reply.status != 200:
                    logger.debug("[innerspace-cm] Logout answered HTTP %s", reply.status)
        await session.close()

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

    def _url(self, path: str, operation: str) -> URL:
        """Join ``path`` to the console origin, refusing any path that could leave it or re-target it."""
        if self._origin is not None and (
            isinstance(path, str)
            and _SAFE_PATH.fullmatch(path)
            and not any(segment in (".", "..") for segment in path.split("/"))
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
        url: URL,
        *,
        operation: str,
        headers: dict[str, str],
        json_body: Any = None,
    ) -> _Reply:
        """Send one request, never following a redirect, and read the whole answer."""
        failure: UniFiConnectionError | None = None
        cause = ""
        try:
            async with session.request(
                method,
                url,
                headers={"Accept": "application/json", **headers},
                json=json_body,
                allow_redirects=False,
            ) as response:
                status = response.status
                body = await response.read()
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
        try:
            payload, is_json = _json.loads(body), True
        except ValueError:
            payload, is_json = None, False
        return _Reply(status, payload, is_json, token.value if token else None, csrf)

    async def _login(self, session: aiohttp.ClientSession) -> _SessionAuth:
        """Log in on ``session`` and return the new session cookie and CSRF token. Caller holds the lock."""
        operation = "InnerSpace console login"
        reply = await self._send(
            session,
            "POST",
            LOGIN_PATH,
            self._url(LOGIN_PATH, operation),
            operation=operation,
            headers={},
            json_body={"username": self._username, "password": self._password},
        )
        if reply.status == 200 and reply.token and reply.csrf:
            return _SessionAuth(token=reply.token, csrf=reply.csrf)
        if reply.status in (401, 403):
            raise UniFiAuthError(_REJECTED)
        if reply.status == 429:
            raise UniFiRateLimitError(_RATE_LIMITED)
        raise UniFiConnectionError(f"{operation}: the console answered HTTP {reply.status} without a session")

    async def _relogin(self, refused: _SessionAuth, operation: str) -> None:
        """Replace a refused session once, however many callers saw it refused.

        Only the first caller under the lock logs in; the others find a
        different session in place and retry with it. A failed login drops the
        session for every caller and, when the console rejected it, opens the
        cool-down.
        """
        async with self._auth_lock:
            if not self.is_connected:
                error = self._unavailable(operation)
            elif self._auth != refused:
                return
            else:
                logger.info("[innerspace-cm] %s: session refused; logging in again", operation)
                failure: Exception | None = None
                try:
                    self._auth = await self._login(self._session)
                except UniFiError as exc:
                    failure = exc
                if failure is None:
                    return
                await self._drop_session(failure)
                error = self._unavailable(operation)
        raise error

    async def _reject_session(self, refused: _SessionAuth, operation: str) -> None:
        """A session issued moments ago was refused again: drop it and stop."""
        async with self._auth_lock:
            if self._auth == refused:
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
    ) -> Any:
        """Send one request with the session and return the decoded JSON body.

        A refused session is re-established once and the request retried once.
        Every failure raises a typed error with fixed text naming ``operation``.
        """
        if self._origin is None:
            raise self._unavailable(operation)
        url = self._url(path, operation)
        if params:
            url = url.with_query(dict(params))
        auth, session = self._auth, self._session
        if auth is None or session is None or self._closed:
            raise self._unavailable(operation)
        reply = await self._send(
            session, method, path, url, operation=operation, headers=auth.headers(), json_body=json
        )
        if not _session_refused(reply):
            return self._interpret(reply, operation)

        await self._relogin(auth, operation)
        auth, session = self._auth, self._session
        if auth is None or session is None:
            raise self._unavailable(operation)
        reply = await self._send(
            session, method, path, url, operation=operation, headers=auth.headers(), json_body=json
        )
        if reply.status == 401:
            await self._reject_session(auth, operation)
        if _session_refused(reply):
            raise UniFiPermissionError(f"{operation}: {_PERMISSION}")
        return self._interpret(reply, operation)

    @staticmethod
    def _interpret(reply: _Reply, operation: str) -> Any:
        status = reply.status
        if 200 <= status < 300:
            if not reply.is_json:
                raise UniFiMalformedResponseError(f"{operation}: the console returned a response that is not JSON")
            return reply.payload
        if 300 <= status < 400:
            raise InnerSpaceHttpError(
                f"{operation}: the console answered with an unexpected redirect (HTTP {status}); not followed",
                status=status,
            )
        if status == 404:
            raise UniFiNotFoundError("route", "InnerSpace", f"{operation}: InnerSpace route not found")
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
