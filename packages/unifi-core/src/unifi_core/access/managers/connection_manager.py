"""Connection management for UniFi Access.

Handles authentication and communication with the UniFi Access controller
via two independent auth paths:

1. **API key path** -- uses ``py-unifi-access`` (``UnifiAccessApiClient``) on the
   dedicated Access API port (default 12445).
2. **Proxy session path** -- logs in via ``/api/auth/login`` on the UniFi OS
   Console (port 443) and proxies requests through
   ``/proxy/access/api/v2/...`` with cookie + CSRF token.

At least one path must succeed during :meth:`initialize`; otherwise it
returns ``False`` and records :attr:`last_connection_error`.  Managers
decorated with :func:`reconnects_on_demand` then make one rate-limited
reconnect attempt before an operation while the controller stays
unreachable, and an authentication rejection pauses those attempts on an
escalating cool-down so repeated calls cannot lock the account out.  When both
are available the caller can choose which path to use per-request (API client
is generally preferred for supported endpoints; the proxy path covers
everything else).
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import logging
import ssl
import time
from typing import Any, Awaitable, Callable, Dict, TypeVar

import aiohttp

from unifi_core.auth import AuthenticationStatus, AuthMethod
from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError, UniFiRateLimitError
from unifi_core.retry import RetryPolicy, retry_with_backoff
from unifi_core.support_bundle import (
    ConnectivityProbe,
    SafeConnectionAttempt,
    connection_attempt_failed,
    connection_attempt_not_configured,
    connection_attempt_started,
    connection_attempt_succeeded,
    connectivity_http_outcome,
    connectivity_probe_result,
)
from unifi_core.support_transport import no_retry_support_request

logger = logging.getLogger(__name__)

# Automatic reconnects make one attempt per interval, each bounded by a timeout,
# so a controller that stays down costs at most one short wait per interval
# instead of a wait on every call.
_RECONNECT_MIN_INTERVAL_SECONDS = 30.0
_CONNECT_ATTEMPT_TIMEOUT_SECONDS = 15.0

# Auth-circuit cool-down: a rejected login blocks automatic reconnects for the
# base interval, doubling per consecutive rejection up to the cap, then allows
# one half-open attempt. Retrying a rejected login on every call is what locks
# controller accounts out.
_RECONNECT_BLOCK_BASE_SECONDS = 60.0
_RECONNECT_BLOCK_MAX_SECONDS = 900.0

_PROXY_REJECTED_STATUSES = frozenset({401, 403})


class AccessUnavailableError(UniFiConnectionError):
    """No auth path can serve the operation; carries the last connection failure."""


class AccessConnectionManager:
    """Manages the dual-path connection to the UniFi Access controller.

    Parameters
    ----------
    host:
        IP or hostname of the UniFi OS Console running Access.
    username:
        Local admin username (required for proxy path).
    password:
        Local admin password (required for proxy path).
    port:
        HTTPS port for the UniFi OS Console (default 443).
    verify_ssl:
        Whether to verify the server's TLS certificate.
    api_key:
        Optional API key for the official Access API (port ``api_port``).
    api_port:
        Port for the ``py-unifi-access`` API (default 12445).
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        verify_ssl: bool = False,
        api_key: str | None = None,
        api_port: int = 12445,
    ) -> None:
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.verify_ssl = verify_ssl

        # Path 1: py-unifi-access (API key auth on dedicated port)
        self._api_client: Any | None = None  # UnifiAccessApiClient
        self._api_key = api_key
        self._api_port = api_port
        self._api_session: aiohttp.ClientSession | None = None

        # Path 2: Proxy session (cookie + CSRF on UniFi OS Console port)
        self._proxy_session: aiohttp.ClientSession | None = None
        self._csrf_token: str = ""
        self._auth_lock = asyncio.Lock()

        # State
        self._api_client_available = False
        self._proxy_available = False
        self._initialized = False
        self._last_connection_error: str | None = None
        self._path_failures: list[BaseException] = []
        self._last_attempt_at: float | None = None
        self._reconnect_lock = asyncio.Lock()
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0
        self._reconnect_callbacks: list[Callable[[], Awaitable[None]]] = []
        self._closed = False
        self._initialize_attempted = False
        self._support_attempt = SafeConnectionAttempt().model_dump(mode="json")
        self._api_support_attempt = (
            SafeConnectionAttempt().model_dump(mode="json") if api_key else connection_attempt_not_configured()
        )
        self._proxy_support_attempt = (
            SafeConnectionAttempt().model_dump(mode="json")
            if username and password
            else connection_attempt_not_configured()
        )

    # ------------------------------------------------------------------
    # SSL helper
    # ------------------------------------------------------------------

    @functools.cached_property
    def _ssl_context(self) -> ssl.SSLContext | bool:
        """Return an SSL context appropriate for the current verify_ssl setting.

        Cached to avoid recreating the SSL context (and reloading the CA bundle)
        on every request.
        """
        if self.verify_ssl:
            return True
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE
        return ctx

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Authenticate via API key and/or proxy session.

        Tries both paths independently.  Uses ``retry_with_backoff`` from
        :mod:`unifi_core.retry` so transient network errors during startup
        are retried; a rejected login is not retried and opens the auth
        circuit instead.

        Returns ``True`` when at least one path succeeds, ``False`` otherwise.
        On failure :attr:`last_connection_error` says whether credentials are
        missing, the controller rejected them, or it could not be reached.
        """
        self._closed = False
        self._initialize_attempted = True
        if self._initialized and (self._api_client_available or self._proxy_available):
            return True

        self._support_attempt = connection_attempt_started()
        if not self._credentials_configured():
            error = UniFiConnectionError(
                "No UniFi Access credentials are configured. Set an API key or a username and password."
            )
            self._record_connect_failure(error)
            return False

        policy = RetryPolicy(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            retryable_exceptions=(UniFiConnectionError,),
        )
        try:
            await retry_with_backoff(self._connect_once, policy=policy)
        except Exception as exc:
            self._record_connect_failure(exc)
            return False
        finally:
            self._last_attempt_at = time.monotonic()
        self._mark_connected()
        return True

    async def reconnect(self) -> bool:
        """Make one automatic reconnect attempt when one is due.

        Returns ``True`` when connected afterwards.  Skips the attempt while
        connected, after :meth:`close`, during the auth cool-down, or within
        the minimum interval since the last attempt.  Registered reconnect
        callbacks run after a successful attempt.
        """
        if not self.reconnect_due:
            return self.is_connected
        async with self._reconnect_lock:
            if not self.reconnect_due:
                return self.is_connected
            logger.info("[access-cm] Attempting automatic reconnect to UniFi Access at %s", self.host)
            self._support_attempt = connection_attempt_started()
            try:
                await self._connect_once()
            except Exception as exc:
                self._record_connect_failure(exc)
                return False
            finally:
                self._last_attempt_at = time.monotonic()
            self._mark_connected()
        await self._run_reconnect_callbacks()
        return True

    @property
    def reconnect_due(self) -> bool:
        """Whether an automatic reconnect attempt would run now.

        Only a manager whose owner has called :meth:`initialize` reconnects;
        one that was never started stays inert.
        """
        if not self._initialize_attempted or self._closed or self.is_connected:
            return False
        if not self._credentials_configured():
            return False
        if self._reconnect_block_remaining() > 0:
            return False
        return self._reconnect_interval_remaining() <= 0

    def add_reconnect_callback(self, callback: Callable[[], Awaitable[None]]) -> None:
        """Run ``callback`` after each successful automatic reconnect."""
        self._reconnect_callbacks.append(callback)

    async def _run_reconnect_callbacks(self) -> None:
        for callback in list(self._reconnect_callbacks):
            try:
                await callback()
            except Exception as exc:
                logger.error("[access-cm] Reconnect callback failed: %s", type(exc).__name__)

    def _credentials_configured(self) -> bool:
        return self.authentication_status.configured(AuthMethod.API_KEY_ONLY) or bool(self.username and self.password)

    async def _connect_once(self) -> None:
        """Try every configured path once, bounded by the attempt timeout.

        Raises :class:`UniFiAuthError` when a path was rejected and none
        connected, and :class:`UniFiConnectionError` when none could be
        reached.
        """
        self._path_failures = []
        try:
            async with asyncio.timeout(_CONNECT_ATTEMPT_TIMEOUT_SECONDS):
                await self._try_api_client()
                await self._try_proxy_session()
        except asyncio.CancelledError:
            await self._discard_unavailable_sessions()
            raise
        except TimeoutError:
            await self._discard_unavailable_sessions()
            raise UniFiConnectionError(
                f"Timed out after {_CONNECT_ATTEMPT_TIMEOUT_SECONDS:.0f}s connecting to UniFi Access at "
                f"{self.host}. Check that the controller is reachable."
            ) from None
        if self._api_client_available or self._proxy_available:
            return
        if any(self._is_rejected_login(failure) for failure in self._path_failures):
            raise UniFiAuthError(self._rejected_message())
        raise UniFiConnectionError(self._unreachable_message())

    async def _discard_unavailable_sessions(self) -> None:
        """Close sessions left behind by a path cancelled mid-attempt."""
        if not self._api_client_available and self._api_session is not None:
            if not self._api_session.closed:
                await self._api_session.close()
            self._api_session = None
            self._api_client = None
        if not self._proxy_available and self._proxy_session is not None:
            if not self._proxy_session.closed:
                await self._proxy_session.close()
            self._proxy_session = None

    def _mark_connected(self) -> None:
        self._initialized = True
        self._last_connection_error = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0
        self._support_attempt = connection_attempt_succeeded()
        logger.info(
            "[access-cm] Connected to UniFi Access at %s (api_client=%s, proxy=%s)",
            self.host,
            self._api_client_available,
            self._proxy_available,
        )

    def _record_connect_failure(self, exc: Exception) -> None:
        self._support_attempt = connection_attempt_failed(exc)
        self._last_connection_error = str(exc)
        self._initialized = False
        logger.error("[access-cm] Failed to connect to UniFi Access: %s", exc)
        if isinstance(exc, UniFiAuthError):
            self._block_automatic_reconnect()

    def _block_automatic_reconnect(self) -> None:
        """Open the auth circuit with an escalating cool-down (half-open after expiry)."""
        self._reconnect_block_count += 1
        cooldown = min(
            _RECONNECT_BLOCK_BASE_SECONDS * (2 ** (self._reconnect_block_count - 1)),
            _RECONNECT_BLOCK_MAX_SECONDS,
        )
        self._reconnect_block_until = time.monotonic() + cooldown
        logger.error(
            "[access-cm] Automatic reconnect blocked after the controller rejected the credentials; "
            "the next attempt is allowed in %.0f seconds.",
            cooldown,
        )

    def _reconnect_block_remaining(self) -> float:
        return max(0.0, self._reconnect_block_until - time.monotonic())

    def _reconnect_interval_remaining(self) -> float:
        if self._last_attempt_at is None:
            return 0.0
        return max(0.0, self._last_attempt_at + _RECONNECT_MIN_INTERVAL_SECONDS - time.monotonic())

    @staticmethod
    def _is_rejected_login(error: BaseException) -> bool:
        if isinstance(error, (UniFiAuthError, UniFiRateLimitError)):
            return True
        try:
            from unifi_access_api import ApiAuthError, ApiForbiddenError, ApiRateLimitError
        except ImportError:  # pragma: no cover - the [access] extra ships the SDK
            return False
        return isinstance(error, (ApiAuthError, ApiForbiddenError, ApiRateLimitError))

    def _configured_paths(self) -> list[str]:
        paths = []
        if self.authentication_status.configured(AuthMethod.API_KEY_ONLY):
            paths.append(f"API key on port {self._api_port}")
        if self.username and self.password:
            paths.append(f"username/password on port {self.port}")
        return paths

    def _unreachable_message(self) -> str:
        return (
            f"Could not reach or authenticate to UniFi Access at {self.host} "
            f"(tried {' and '.join(self._configured_paths())}). Check that the controller is reachable "
            "and the configured credentials are valid."
        )

    def _rejected_message(self) -> str:
        return (
            f"UniFi Access at {self.host} rejected the configured credentials "
            f"(tried {' and '.join(self._configured_paths())}). Check the username/password or API key."
        )

    @property
    def last_connection_error(self) -> str | None:
        """Why the last connection attempt failed, or ``None`` after a success."""
        return self._last_connection_error

    def unavailable_error(self, message: str) -> AccessUnavailableError:
        """Build the error a manager raises when its auth path is unavailable.

        When a connection attempt failed, the reason is appended so tool
        callers see why Access is unavailable, plus when the next automatic
        reconnect may run.
        """
        if not self._last_connection_error:
            return AccessUnavailableError(message)
        detail = f"{message}: {self._last_connection_error}"
        blocked = self._reconnect_block_remaining()
        if blocked > 0:
            detail += f" Automatic reconnect is paused for {blocked:.0f}s after the rejected login."
        elif not self._closed and not self.is_connected:
            detail += (
                f" The next automatic reconnect attempt is allowed in {self._reconnect_interval_remaining():.0f}s."
            )
        return AccessUnavailableError(detail)

    async def _try_api_client(self) -> None:
        """Attempt to initialise the py-unifi-access API client."""
        if not self.authentication_status.configured(AuthMethod.API_KEY_ONLY):
            self._api_support_attempt = connection_attempt_not_configured()
            logger.debug("[access-cm] No API key configured; skipping API client path.")
            return

        self._api_support_attempt = connection_attempt_started()
        try:
            from unifi_access_api import UnifiAccessApiClient

            connector = aiohttp.TCPConnector(ssl=self._ssl_context)
            self._api_session = aiohttp.ClientSession(connector=connector)
            self._api_client = UnifiAccessApiClient(
                host=f"https://{self.host}:{self._api_port}",
                api_token=self._api_key,
                session=self._api_session,
                verify_ssl=self.verify_ssl,
            )
            await self._api_client.authenticate()
            self._api_client_available = True
            self._api_support_attempt = connection_attempt_succeeded()
            logger.info("[access-cm] API client authenticated on port %s", self._api_port)
        except Exception as exc:
            self._path_failures.append(exc)
            self._api_support_attempt = connection_attempt_failed(exc)
            logger.warning(
                "[access-cm] API client auth failed (non-fatal, will try proxy): %s",
                exc,
            )
            # Clean up the failed session
            if self._api_session and not self._api_session.closed:
                await self._api_session.close()
                self._api_session = None
            self._api_client = None
            self._api_client_available = False

    async def _try_proxy_session(self) -> None:
        """Attempt to establish a proxy session via UniFi OS Console login."""
        if not self.username or not self.password:
            self._proxy_support_attempt = connection_attempt_not_configured()
            logger.debug("[access-cm] No username/password configured; skipping proxy path.")
            return

        self._proxy_support_attempt = connection_attempt_started()
        try:
            self._proxy_session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._ssl_context),
                cookie_jar=aiohttp.CookieJar(unsafe=True),
            )
            await self._proxy_login()
            self._proxy_available = True
            self._proxy_support_attempt = connection_attempt_succeeded()
            logger.info("[access-cm] Proxy session established via %s:%s", self.host, self.port)
        except Exception as exc:
            self._path_failures.append(exc)
            self._proxy_support_attempt = connection_attempt_failed(exc)
            logger.warning(
                "[access-cm] Proxy login failed (non-fatal if API client available): %s",
                exc,
            )
            if self._proxy_session and not self._proxy_session.closed:
                await self._proxy_session.close()
                self._proxy_session = None
            self._proxy_available = False

    async def _proxy_login(self) -> None:
        """Authenticate to the UniFi OS Console and store the CSRF token.

        The session's cookie jar automatically stores the auth cookie.
        """
        url = f"https://{self.host}:{self.port}/api/auth/login"
        payload = {"username": self.username, "password": self.password}

        async with self._proxy_session.post(url, json=payload) as resp:
            if resp.status != 200:
                body = ""
                try:
                    body = await resp.text()
                except Exception:
                    pass
                detail = f"Proxy login failed: HTTP {resp.status}{(' — ' + body[:200]) if body else ''}"
                if resp.status in _PROXY_REJECTED_STATUSES:
                    raise UniFiAuthError(detail)
                if resp.status == 429:
                    raise UniFiRateLimitError(detail)
                raise UniFiConnectionError(detail)
            self._csrf_token = resp.headers.get("x-updated-csrf-token", resp.headers.get("x-csrf-token", ""))
            logger.debug("[access-cm] Proxy login successful, CSRF token obtained.")

    # ------------------------------------------------------------------
    # Access Developer API request helper
    # ------------------------------------------------------------------

    async def developer_request(
        self,
        method: str,
        path: str,
        *,
        operation: str,
        json: Any = None,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Request the official Access Developer API with Bearer auth.

        The Access Developer API is served on ``api_port`` and uses
        ``Authorization: Bearer``. This differs from Network's public
        Integration API, which uses ``X-API-Key``.
        """
        remediation = (
            "Create a UniFi Access API token and set UNIFI_ACCESS_API_KEY (or UNIFI_API_KEY) for the Access MCP server."
        )
        if not self._api_key:
            raise UniFiAuthError(f"{operation} requires a UniFi Access API token. {remediation}")
        if not self.has_api_client or self._api_session is None:
            raise UniFiAuthError(
                f"{operation} requires an authenticated UniFi Access Developer API session. "
                f"The configured token did not authenticate on port {self._api_port}. {remediation}"
            )

        url = f"https://{self.host}:{self._api_port}/api/v1/developer/{path.lstrip('/')}"
        headers = {
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self._api_key}",
        }
        try:
            async with self._api_session.request(
                method,
                url,
                headers=headers,
                json=json,
                params=params,
                ssl=self._ssl_context,
                timeout=aiohttp.ClientTimeout(total=10),
            ) as resp:
                try:
                    payload = await resp.json(content_type=None)
                except (ValueError, aiohttp.ContentTypeError) as exc:
                    body = await resp.text()
                    raise UniFiConnectionError(
                        f"{operation} failed: HTTP {resp.status} {method} {url} — "
                        f"invalid JSON response{(': ' + body[:200]) if body else ''}"
                    ) from exc

                message = ""
                if isinstance(payload, dict):
                    message = str(payload.get("msg") or payload.get("message") or payload.get("code") or "")
                if resp.status in (401, 403):
                    raise UniFiAuthError(
                        f"{operation} requires a valid UniFi Access API token with visitor access: "
                        f"HTTP {resp.status}{(' — ' + message) if message else ''}. {remediation}"
                    )
                if resp.status != 200:
                    raise UniFiConnectionError(
                        f"{operation} failed: HTTP {resp.status} {method} {url}{(' — ' + message) if message else ''}"
                    )
                if not isinstance(payload, dict):
                    raise UniFiConnectionError(f"{operation} failed: unexpected Access API response shape")
                if payload.get("code") != "SUCCESS":
                    raise UniFiConnectionError(
                        f"{operation} failed: Access API code {payload.get('code', 'UNKNOWN')}"
                        f"{(' — ' + message) if message else ''}"
                    )
                if "data" not in payload:
                    raise UniFiConnectionError(f"{operation} failed: Access API response is missing data")
                return payload["data"]
        except (UniFiAuthError, UniFiConnectionError):
            raise
        except (TimeoutError, aiohttp.ClientError, OSError) as exc:
            raise UniFiConnectionError(f"{operation} failed: {exc}") from exc

    # ------------------------------------------------------------------
    # Proxy request helpers
    # ------------------------------------------------------------------

    async def _proxy_request_impl(self, method: str, url: str, label: str, **kwargs: Any) -> Dict[str, Any]:
        """Shared proxy request implementation with 401 re-auth.

        A rejected re-login drops the proxy session and opens the auth
        circuit, so later calls do not repeat the login against the account.
        """
        try:
            return await self._proxy_request_with_reauth(method, url, label, **kwargs)
        except (UniFiAuthError, UniFiRateLimitError):
            await self._drop_rejected_proxy_session()
            raise self.unavailable_error(f"{label} re-authentication failed") from None

    async def _proxy_request_with_reauth(self, method: str, url: str, label: str, **kwargs: Any) -> Dict[str, Any]:
        """Send one proxy request, re-authenticating once on HTTP 401.

        Parameters
        ----------
        method:
            HTTP method (GET, POST, PUT, DELETE).
        url:
            Fully-qualified URL to request.
        label:
            Human-readable label for error messages (e.g. "Proxy" or "ULP proxy").
        **kwargs:
            Extra keyword arguments forwarded to ``aiohttp.ClientSession.request``.
        """
        headers = {"X-CSRF-Token": self._csrf_token}
        token_before = self._csrf_token

        async with self._proxy_session.request(method, url, headers=headers, **kwargs) as resp:
            if resp.status == 401:
                async with self._auth_lock:
                    # Double-check: skip re-auth if another coroutine already refreshed
                    if not self._proxy_available:
                        raise self.unavailable_error(f"{label} re-authentication failed")
                    if self._csrf_token == token_before:
                        logger.info("[access-cm] %s session expired, re-authenticating...", label)
                        await self._proxy_login()

                retry_headers = {"X-CSRF-Token": self._csrf_token}
                async with self._proxy_session.request(method, url, headers=retry_headers, **kwargs) as retry_resp:
                    if retry_resp.status != 200:
                        raise UniFiConnectionError(
                            f"{label} request failed after re-auth: HTTP {retry_resp.status} {method} {url}"
                        )
                    payload = await retry_resp.json()
                    self._raise_for_api_error(payload, method, url, label)
                    return payload

            if resp.status != 200:
                body = ""
                try:
                    body = await resp.text()
                except Exception:
                    pass
                raise UniFiConnectionError(
                    f"{label} request failed: HTTP {resp.status} {method} {url}{(' — ' + body[:200]) if body else ''}"
                )
            payload = await resp.json()
            self._raise_for_api_error(payload, method, url, label)
            return payload

    async def _drop_rejected_proxy_session(self) -> None:
        self._proxy_available = False
        if self._proxy_session is not None and not self._proxy_session.closed:
            await self._proxy_session.close()
        self._proxy_session = None
        if not self._api_client_available:
            self._initialized = False
        self._last_connection_error = self._rejected_message()
        self._last_attempt_at = time.monotonic()
        logger.error("[access-cm] Proxy re-authentication was rejected; dropping the proxy session.")
        self._block_automatic_reconnect()

    @staticmethod
    def _raise_for_api_error(payload: Any, method: str, url: str, label: str) -> None:
        """Raise when Access returns an application-level error in a 200 response."""
        if not isinstance(payload, dict) or "code" not in payload:
            return

        code = payload.get("code")
        if code in (0, "0", 1, "1", None):
            return

        try:
            if int(code) >= 0:
                return
        except (TypeError, ValueError):
            pass

        code_s = payload.get("codeS") or payload.get("error") or "UNKNOWN"
        message = payload.get("msg") or payload.get("message") or payload.get("error") or "Access API error"
        raise UniFiConnectionError(f"{label} request failed: API code {code} {code_s} {method} {url} — {message}")

    async def proxy_request(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a request via the UniFi OS proxy path.

        Parameters
        ----------
        method:
            HTTP method (GET, POST, PUT, DELETE).
        path:
            API path relative to ``/proxy/access/api/v2/``.
        **kwargs:
            Extra keyword arguments forwarded to ``aiohttp.ClientSession.request``
            (e.g. ``json=``, ``params=``).

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        UniFiConnectionError
            If the proxy session is not available.
        """
        if not self._proxy_available or self._proxy_session is None:
            raise self.unavailable_error("Proxy session is not available")

        url = f"https://{self.host}:{self.port}/proxy/access/api/v2/{path.lstrip('/')}"
        return await self._proxy_request_impl(method, url, "Proxy", **kwargs)

    async def proxy_request_ulp(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a request via the ULP-Go sub-proxy path.

        The UniFi Access user management API lives under a different
        sub-proxy: ``/proxy/access/ulp-go/api/v2/...`` rather than
        ``/proxy/access/api/v2/...``.

        Parameters
        ----------
        method:
            HTTP method (GET, POST, PUT, DELETE).
        path:
            API path relative to ``/proxy/access/ulp-go/api/v2/``.
        **kwargs:
            Extra keyword arguments forwarded to ``aiohttp.ClientSession.request``
            (e.g. ``json=``, ``params=``).

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        UniFiConnectionError
            If the proxy session is not available.
        """
        if not self._proxy_available or self._proxy_session is None:
            raise self.unavailable_error("Proxy session is not available")

        url = f"https://{self.host}:{self.port}/proxy/access/ulp-go/api/v2/{path.lstrip('/')}"
        return await self._proxy_request_impl(method, url, "ULP proxy", **kwargs)

    async def proxy_request_users(self, method: str, path: str, **kwargs: Any) -> Dict[str, Any]:
        """Make a request via the Users proxy path.

        User management on UniFi OS is handled by the dedicated Users
        application at ``/proxy/users/api/v2/...``, not the Access
        proxy.

        Parameters
        ----------
        method:
            HTTP method (GET, POST, PUT, DELETE).
        path:
            API path relative to ``/proxy/users/api/v2/``.
        **kwargs:
            Extra keyword arguments forwarded to ``aiohttp.ClientSession.request``.

        Returns
        -------
        dict
            Parsed JSON response body.

        Raises
        ------
        UniFiConnectionError
            If the proxy session is not available.
        """
        if not self._proxy_available or self._proxy_session is None:
            raise self.unavailable_error("Proxy session is not available")

        url = f"https://{self.host}:{self.port}/proxy/users/api/v2/{path.lstrip('/')}"
        return await self._proxy_request_impl(method, url, "Users proxy", **kwargs)

    # ------------------------------------------------------------------
    # Response helpers
    # ------------------------------------------------------------------

    @staticmethod
    def extract_data(response: Any) -> Any:
        """Unwrap the ``{"data": ...}`` envelope common in Access API responses.

        Returns ``response["data"]`` when present, otherwise ``response`` itself.
        """
        if isinstance(response, dict):
            return response.get("data", response)
        return response

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def api_port(self) -> int:
        """Return the Access API port."""
        return self._api_port

    @property
    def api_client(self) -> Any | None:
        """Return the :class:`UnifiAccessApiClient` instance, or ``None``."""
        return self._api_client

    @property
    def has_api_key(self) -> bool:
        """Return whether an Access Developer API token is configured."""
        return bool(self._api_key)

    @property
    def authentication_status(self) -> AuthenticationStatus:
        return AuthenticationStatus(
            session_configured=bool(self.username and self.password),
            api_key_configured=self.has_api_key,
            session_available=self.has_proxy,
            api_key_available=self.has_api_client,
        )

    @property
    def has_api_client(self) -> bool:
        """Return ``True`` if the API client path is available."""
        return self._api_client_available and self._api_client is not None

    @property
    def has_proxy(self) -> bool:
        """Return ``True`` if the proxy session path is available."""
        return self._proxy_available and self._proxy_session is not None

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if at least one auth path is initialised."""
        return self._initialized and (self._api_client_available or self._proxy_available)

    def support_status(self) -> dict[str, Any]:
        """Return local connection facts safe for a community support bundle."""
        return {
            "initialized": self._initialized,
            "connected": self.is_connected,
            "tls_verification_enabled": self.verify_ssl,
            "last_attempt": dict(self._support_attempt),
            "developer_api_available": self.has_api_client,
            "proxy_session_available": self.has_proxy,
            "api_token_configured": self.has_api_key,
            "developer_api_attempt": dict(self._api_support_attempt),
            "proxy_session_attempt": dict(self._proxy_support_attempt),
        }

    async def support_connectivity_probe(self) -> ConnectivityProbe:
        """Perform one bounded request through one existing authenticated session."""
        request: tuple[aiohttp.ClientSession, str, dict[str, str]] | None = None
        if self.has_api_client and self._api_session is not None and not self._api_session.closed:
            # The emergency-status endpoint returns one fixed-size state object,
            # avoiding collection materialization for this connectivity check.
            request = (
                self._api_session,
                f"https://{self.host}:{self._api_port}/api/v1/developer/doors/settings/emergency",
                {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"},
            )
        elif self.has_proxy and self._proxy_session is not None and not self._proxy_session.closed:
            request = (
                self._proxy_session,
                f"https://{self.host}:{self.port}/proxy/access/api/v2/access/info",
                {"X-CSRF-Token": self._csrf_token},
            )
        if request is None:
            result = connectivity_probe_result("connection", None)
            logger.info(
                "Support connectivity audit product=access outcome=%s duration=%s",
                result.outcome,
                result.duration_bucket,
            )
            return result

        session, url, headers = request
        started = time.perf_counter()
        try:
            async with session.request(
                "GET",
                url,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=self._ssl_context,
                allow_redirects=False,
                middlewares=(no_retry_support_request,),
            ) as response:
                outcome = connectivity_http_outcome(response.status)
        except TimeoutError:
            outcome = "timeout"
        except (aiohttp.ClientError, OSError):
            outcome = "connection"
        except Exception:
            outcome = "unknown"
        result = connectivity_probe_result(outcome, (time.perf_counter() - started) * 1000)
        logger.info(
            "Support connectivity audit product=access outcome=%s duration=%s",
            result.outcome,
            result.duration_bucket,
        )
        return result

    # ------------------------------------------------------------------
    # Websocket
    # ------------------------------------------------------------------

    def start_websocket(self, handlers: Dict[str, Any], **kwargs: Any) -> Any:
        """Start a websocket connection via the API client.

        Delegates to :meth:`UnifiAccessApiClient.start_websocket`.

        Raises :class:`UniFiConnectionError` if no API client is available.
        """
        if not self.has_api_client:
            raise UniFiConnectionError("Cannot start websocket — API client not available.")
        return self._api_client.start_websocket(handlers, **kwargs)

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Gracefully shut down both sessions and stop automatic reconnects."""
        self._closed = True
        if self._api_client is not None:
            try:
                await self._api_client.close()
            except Exception:
                logger.debug("[access-cm] Error closing API client", exc_info=True)
            self._api_client = None

        if self._api_session is not None and not self._api_session.closed:
            try:
                await self._api_session.close()
            except Exception:
                logger.debug("[access-cm] Error closing API session", exc_info=True)
            self._api_session = None

        if self._proxy_session is not None and not self._proxy_session.closed:
            try:
                await self._proxy_session.close()
            except Exception:
                logger.debug("[access-cm] Error closing proxy session", exc_info=True)
            self._proxy_session = None

        self._api_client_available = False
        self._proxy_available = False
        self._initialized = False
        logger.info("[access-cm] Connection closed.")


_ManagerT = TypeVar("_ManagerT", bound=type)


def reconnects_on_demand(cls: _ManagerT) -> _ManagerT:
    """Give an Access manager one automatic reconnect attempt per operation.

    Every public coroutine method first asks the manager's connection
    manager (``self._cm``) to reconnect when it has no auth path and an
    attempt is due, so a controller that was down at startup is picked up
    without restarting the server.  The attempt runs before the operation
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
        if getattr(cm, "reconnect_due", None) is True:
            await cm.reconnect()
        return await method(self, *args, **kwargs)

    return wrapper
