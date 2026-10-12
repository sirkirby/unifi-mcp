"""Connection management for UniFi Protect.

Handles authentication and communication with the UniFi Protect controller
via the ``uiprotect`` (pyunifiprotect) library.  This is a thin wrapper that
owns the :class:`ProtectApiClient` lifecycle: creation, initial data fetch,
websocket subscription, and graceful shutdown.
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Awaitable, Callable

import aiohttp
from uiprotect import ProtectApiClient
from uiprotect.data import WSSubscriptionMessage
from uiprotect.exceptions import NotAuthorized, NvrError

from unifi_core.auth import AuthenticationStatus, AuthMethod
from unifi_core.connect_attempt import ConnectAttempt
from unifi_core.connection_failure import ControllerConnectionFailed, connection_failure
from unifi_core.exceptions import UniFiConnectionError
from unifi_core.protect.errors import nvr_status
from unifi_core.protect.managers.id_portability import IdPortabilityReport, compare_id_portability
from unifi_core.retry import RetryPolicy, retry_with_backoff
from unifi_core.support_bundle import (
    ConnectivityProbe,
    SafeConnectionAttempt,
    connection_attempt_failed,
    connection_attempt_started,
    connection_attempt_succeeded,
    connectivity_http_outcome,
    connectivity_probe_result,
)
from unifi_core.support_transport import no_retry_support_request

logger = logging.getLogger(__name__)

# How often the bootstrap is fetched again while the connection lives. The
# websocket keeps cameras and events current, but not every NVR field: without
# a re-fetch, firmware_version, is_updating and up_since stay at their values
# from connect time - across a UniFi OS update and reboot of the console.
# Home Assistant's Protect integration re-fetches on the same order.
BOOTSTRAP_REFRESH_SECONDS = 60.0

# Automatic reconnect: when a call finds no client (the controller was down or
# rejected the login at start-up), one connection attempt is made, without the
# start-up back-off. Attempts are spaced at least this far apart, so a
# controller that stays down costs one bounded wait per window rather than one
# per call. Every attempt, the start-up ones included, is cut off after the
# timeout: the SDK's own session would otherwise wait minutes on a controller
# that accepts the connection and never answers.
RECONNECT_MIN_INTERVAL_SECONDS = 30.0
RECONNECT_ATTEMPT_TIMEOUT_SECONDS = 30.0

# Auth-circuit cool-down, as in Network: a rejected or rate-limited login
# blocks automatic reconnects for the base interval, doubling per consecutive
# failure up to the cap, so repeated calls cannot lock the account out. The
# circuit half-opens on the timer instead of requiring a process restart.
_RECONNECT_BLOCK_BASE_SECONDS = 60.0
_RECONNECT_BLOCK_MAX_SECONDS = 900.0

# uiprotect reports a rate-limited login as NvrError with the status in its
# message ("... - Status: 429 - Reason: ...").
_RATE_LIMITED_STATUS_RE = re.compile(r"Status: 429(?!\d)")


def _is_terminal_auth_error(error: BaseException) -> bool:
    """A login the controller rejected or rate-limited; retrying it risks a lockout."""
    if isinstance(error, NotAuthorized):
        return True
    return isinstance(error, NvrError) and _RATE_LIMITED_STATUS_RE.search(str(error)) is not None


class ProtectConnectionManager:
    """Manages the connection to the UniFi Protect controller.

    Parameters
    ----------
    host:
        IP or hostname of the UniFi OS Console running Protect.
    username:
        Local admin username.
    password:
        Local admin password.
    port:
        HTTPS port (default 443).
    site:
        UniFi site name (metadata only — Protect uses a single site).
    verify_ssl:
        Whether to verify the server's TLS certificate.
    api_key:
        Optional API key for official Protect API endpoints.
    bootstrap_refresh_seconds:
        How often the bootstrap is fetched again after :meth:`initialize`;
        ``0`` turns the re-fetch off.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        port: int = 443,
        site: str = "default",
        verify_ssl: bool = False,
        api_key: str | None = None,
        bootstrap_refresh_seconds: float = BOOTSTRAP_REFRESH_SECONDS,
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.site = site
        self.verify_ssl = verify_ssl
        self._api_key = api_key

        self._client: ProtectApiClient | None = None
        self._ws_unsub: Callable[[], None] | None = None
        self._initialized = False
        self._initialization_failure: ControllerConnectionFailed | None = None
        self._support_attempt = SafeConnectionAttempt().model_dump(mode="json")
        self._bootstrap_refresh_seconds = bootstrap_refresh_seconds
        self._refresh_task: asyncio.Task[None] | None = None

        self._connect_lock = asyncio.Lock()
        self._attempt = ConnectAttempt()
        self._connect_hooks: list[Callable[[], Awaitable[None]]] = []
        self._closed = False
        self._clock: Callable[[], float] = time.monotonic
        self._reconnect_min_interval = RECONNECT_MIN_INTERVAL_SECONDS
        self._reconnect_attempt_timeout = RECONNECT_ATTEMPT_TIMEOUT_SECONDS
        self._last_connect_attempt_at: float | None = None
        self._last_failure_class: str | None = None
        self._reconnect_block_class: str | None = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Create the :class:`ProtectApiClient`, authenticate, and fetch bootstrap data.

        Uses ``retry_with_backoff`` from :mod:`unifi_core.retry` so transient
        network errors during startup are retried with exponential back-off.
        A login the controller rejects is not retried: it opens the auth
        circuit, which holds automatic reconnects back for the cool-down.

        This is an explicit start, so it ignores the reconnect window and the
        auth circuit; :meth:`ensure_connected` is the automatic path. It runs
        as the manager's one connection attempt, so a server can call it in
        the background and tool calls wait on it within a bound.

        Returns ``True`` on success, ``False`` on failure.
        """
        if self._initialized and self._client is not None:
            return True
        if self._attempt.in_progress:
            # Let an on-demand attempt finish rather than run a second one.
            if await self._attempt.join():
                return True
        self._attempt.start(self._initialize_with_retries, name="protect-connect")
        return await self._attempt.join()

    async def _initialize_with_retries(self) -> bool:
        policy = RetryPolicy(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            retryable_exceptions=(Exception,),
        )
        rejected: list[Exception] = []

        async def _connect() -> None:
            try:
                async with asyncio.timeout(self._reconnect_attempt_timeout):
                    await self._connect_once()
            except Exception as exc:
                if _is_terminal_auth_error(exc):
                    # Returning ends the back-off: retrying a rejected login
                    # only brings a controller lockout closer.
                    rejected.append(exc)
                    return
                raise

        async with self._connect_lock:
            if self._initialized and self._client is not None:
                return True
            self._closed = False
            self._support_attempt = connection_attempt_started()
            try:
                await retry_with_backoff(_connect, policy=policy)
            except Exception as exc:
                self._connection_failed(exc)
                # Class only: SDK and transport messages can carry controller text.
                logger.error(
                    "[protect-cm] Failed to connect to UniFi Protect at %s:%s: %s",
                    self.host,
                    self.port,
                    type(exc).__name__,
                )
                return False
            if rejected:
                self._connection_failed(rejected[-1])
                return False
            await self._connection_succeeded()
            logger.info(
                "[protect-cm] Connected to UniFi Protect at %s:%s",
                self.host,
                self.port,
            )
            return True

    async def ensure_connected(self) -> bool:
        """Make one connection attempt when no client is available.

        The automatic counterpart of :meth:`initialize`, for callers that find
        no client because the controller was unreachable or rejected the
        login when the server started. It makes a single attempt with no
        back-off, at most once per reconnect window, and none at all while
        the auth circuit's cool-down runs or after :meth:`close`. Concurrent
        callers share one attempt, including a start-up :meth:`initialize`
        still running, and wait for it only within the attempt's wait window;
        the attempt itself continues in the background.

        Returns ``True`` when a client is available afterwards.
        """
        if self._initialized and self._client is not None:
            return True
        if not self._attempt.in_progress:
            if not self._reconnect_allowed():
                return False
            self._attempt.start(self._reconnect_once, name="protect-reconnect")
        await self._attempt.wait()
        return self._initialized and self._client is not None

    async def _reconnect_once(self) -> bool:
        async with self._connect_lock:
            if self._initialized and self._client is not None:
                return True
            if not self._reconnect_allowed():
                return False
            logger.info("[protect-cm] Not connected to UniFi Protect; attempting to reconnect.")
            self._support_attempt = connection_attempt_started()
            try:
                async with asyncio.timeout(self._reconnect_attempt_timeout):
                    await self._connect_once()
            except Exception as exc:
                self._connection_failed(exc)
                if not _is_terminal_auth_error(exc):
                    logger.warning(
                        "[protect-cm] Reconnect to UniFi Protect failed: %s. "
                        "The next attempt is allowed in %.0f seconds.",
                        type(exc).__name__,
                        self._reconnect_min_interval,
                    )
                return False
            if self._closed:
                # close() ran while the attempt was in flight.
                client, self._client = self._client, None
                if client is not None:
                    await self._dispose_client(client)
                return False
            await self._connection_succeeded()
            logger.info("[protect-cm] Reconnected to UniFi Protect at %s:%s", self.host, self.port)
            return True

    def add_connect_hook(self, hook: Callable[[], Awaitable[None]]) -> None:
        """Run ``hook`` after every successful connect, at start-up or on reconnect.

        For what a normal start brings up beyond the connection itself, such
        as the event websocket listener. A failing hook is logged and does
        not undo the connection.
        """
        self._connect_hooks.append(hook)

    async def _connect_once(self) -> None:
        client = ProtectApiClient(
            host=self.host,
            port=self.port,
            username=self.username,
            password=self.password,
            api_key=self._api_key,
            verify_ssl=self.verify_ssl,
        )
        # update() authenticates + fetches the full bootstrap (NVR, cameras, etc.)
        try:
            await client.update()
        except BaseException:
            # A failed, timed-out or cancelled bootstrap must not orphan the
            # SDK's session when a later attempt creates another client.
            await self._dispose_client(client)
            raise
        self._client = client

    async def _connection_succeeded(self) -> None:
        self._initialized = True
        self._initialization_failure = None
        self._support_attempt = connection_attempt_succeeded()
        self._last_failure_class = None
        self._clear_reconnect_block()
        self._start_bootstrap_refresh()
        for hook in list(self._connect_hooks):
            try:
                await hook()
            except Exception as exc:
                logger.error("[protect-cm] Post-connect step failed: %s", type(exc).__name__)

    def _connection_failed(self, error: BaseException) -> None:
        self._initialized = False
        self._last_failure_class = type(error).__name__
        # The exception can quote NVR responses: keep its category and status only.
        # uiprotect wraps a timed-out request in NvrError; classify it by its cause.
        cause = error.__cause__ if isinstance(error.__cause__, TimeoutError) else error
        self._initialization_failure = connection_failure(
            "Connecting to UniFi Protect failed.", cause, status=nvr_status(error)
        )
        self._support_attempt = connection_attempt_failed(self._initialization_failure)
        self._last_connect_attempt_at = self._clock()
        if _is_terminal_auth_error(error):
            self._block_automatic_reconnect(error)

    def _reconnect_allowed(self) -> bool:
        if self._closed or self._reconnect_block_active():
            return False
        last = self._last_connect_attempt_at
        return last is None or self._clock() - last >= self._reconnect_min_interval

    def _block_automatic_reconnect(self, error: BaseException) -> None:
        """Open the auth circuit with an escalating cool-down (half-open after expiry)."""
        self._reconnect_block_class = type(error).__name__
        self._reconnect_block_count += 1
        cooldown = min(
            _RECONNECT_BLOCK_BASE_SECONDS * (2 ** (self._reconnect_block_count - 1)),
            _RECONNECT_BLOCK_MAX_SECONDS,
        )
        self._reconnect_block_until = self._clock() + cooldown
        logger.error(
            "[protect-cm] Automatic reconnect blocked after the UniFi Protect login was rejected: %s. "
            "Correct the credentials or wait for the controller lockout to clear; "
            "the next reconnect attempt is allowed in %.0f seconds.",
            type(error).__name__,
            cooldown,
        )

    def _reconnect_block_active(self) -> bool:
        return self._reconnect_block_class is not None and self._clock() < self._reconnect_block_until

    def _clear_reconnect_block(self) -> None:
        self._reconnect_block_class = None
        self._reconnect_block_until = 0.0
        self._reconnect_block_count = 0

    @property
    def reconnect_cooldown_active(self) -> bool:
        """True while the auth circuit holds automatic reconnects back."""
        return self._reconnect_block_active()

    def _not_connected_message(self) -> str:
        """Why no client is available: exception class and fixed guidance only."""
        if self._closed:
            return "UniFi Protect connection is not initialized: the connection was closed."
        if self._attempt.in_progress:
            return (
                "UniFi Protect connection is not ready: still connecting to the controller, "
                "which has not answered yet. Check that the controller is reachable from this machine; "
                "the attempt continues in the background and a later call uses the connection once it succeeds."
            )
        if self._reconnect_block_active():
            remaining = max(0.0, self._reconnect_block_until - self._clock())
            return (
                "UniFi Protect connection is not initialized: the controller rejected the login "
                f"({self._reconnect_block_class}). Automatic reconnect is paused for about {remaining:.0f} seconds; "
                "check the Protect username and password, or wait for a login lockout to clear."
            )
        if self._last_failure_class is not None:
            return (
                "UniFi Protect connection is not initialized: the last connection attempt failed "
                f"({self._last_failure_class}). Check that the controller is reachable; "
                "a later call tries to connect again."
            )
        return "ProtectConnectionManager is not initialized. Call initialize() first."

    @property
    def initialization_failure(self) -> ControllerConnectionFailed | None:
        """Why the last connection attempt failed, as a fixed-text error keeping its category and status."""
        return self._initialization_failure

    @staticmethod
    async def _dispose_client(client: ProtectApiClient) -> None:
        for operation in ("async_disconnect_ws", "close_session"):
            try:
                await getattr(client, operation)()
            except Exception as exc:
                logger.debug("[protect-cm] %s failed: %s", operation, type(exc).__name__)

    def _start_bootstrap_refresh(self) -> None:
        if self._bootstrap_refresh_seconds <= 0 or self._refresh_task is not None:
            return
        self._refresh_task = asyncio.get_running_loop().create_task(self._refresh_bootstrap_forever())

    async def refresh_bootstrap(self) -> bool:
        """Fetch the bootstrap again. Returns ``True`` on success.

        A failure (the console rebooting, a dropped session) is logged and
        leaves the last bootstrap in place; the next attempt follows on the
        interval. ``client.update()`` re-authenticates as it needs to.
        """
        if self._client is None:
            return False
        try:
            await self._client.update()
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("[protect-cm] Bootstrap refresh failed: %s", type(exc).__name__)
            return False
        return True

    async def _refresh_bootstrap_forever(self) -> None:
        while True:
            await asyncio.sleep(self._bootstrap_refresh_seconds)
            await self.refresh_bootstrap()

    async def close(self) -> None:
        """Gracefully shut down websocket, client session, and API session."""
        await self._attempt.cancel()
        if self._refresh_task is not None:
            self._refresh_task.cancel()
            try:
                await self._refresh_task
            except (asyncio.CancelledError, Exception):
                pass
            self._refresh_task = None
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[protect-cm] Error unsubscribing websocket", exc_info=True)
            self._ws_unsub = None

        if self._client is not None:
            await self._dispose_client(self._client)
            self._client = None

        self._initialized = False
        self._closed = True
        self._last_connect_attempt_at = None
        self._last_failure_class = None
        self._clear_reconnect_block()
        logger.info("[protect-cm] Connection closed.")

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def has_api_key(self) -> bool:
        """Return ``True`` when a non-empty Protect public API key is configured."""
        return bool(self._api_key and self._api_key.strip())

    def support_status(self) -> dict[str, Any]:
        """Return local connection facts safe for a community support bundle."""
        client_available = self._initialized and self._client is not None
        bootstrap_available = bool(client_available and getattr(self._client, "bootstrap", None) is not None)
        return {
            "initialized": self._initialized,
            "connected": self.is_connected,
            "tls_verification_enabled": self.verify_ssl,
            "last_attempt": dict(self._support_attempt),
            "session_available": client_available,
            "bootstrap_available": bootstrap_available,
            "public_api_key_configured": self.has_api_key,
            "websocket_state": (
                "connected" if self._ws_unsub is not None else "disconnected" if client_available else "unknown"
            ),
        }

    async def support_connectivity_probe(self) -> ConnectivityProbe:
        """Perform one bounded request through the existing private session."""
        client = self._client
        session = getattr(client, "_session", None) if client is not None else None
        if not self._initialized or client is None or session is None or session.closed:
            result = connectivity_probe_result("connection", None)
            logger.info(
                "Support connectivity audit product=protect outcome=%s duration=%s",
                result.outcome,
                result.duration_bucket,
            )
            return result

        started = time.perf_counter()
        try:
            url = client._url.with_path("/proxy/protect/api/nvr")
            async with session.request(
                "GET",
                url,
                headers=client.headers or {},
                timeout=aiohttp.ClientTimeout(total=10),
                ssl=False if not self.verify_ssl else None,
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
            "Support connectivity audit product=protect outcome=%s duration=%s",
            result.outcome,
            result.duration_bucket,
        )
        return result

    @property
    def authentication_status(self) -> AuthenticationStatus:
        return AuthenticationStatus(
            session_configured=bool(self.username and self.password),
            api_key_configured=self.has_api_key,
            session_available=self.is_connected,
            # Bootstrap success does not verify the independently authenticated
            # public API. Public methods enforce/validate it when called.
            api_key_available=None,
        )

    def require_public_api_key(self, operation: str) -> None:
        """Raise an actionable error when a public Integration API call lacks an API key."""
        if self.authentication_status.configured(AuthMethod.API_KEY_ONLY):
            return
        raise ValueError(
            f"Cannot {operation}: UniFi Protect public Integration API access requires an API key. "
            "Set UNIFI_PROTECT_API_KEY or UNIFI_API_KEY and restart the server."
        )

    async def validate_public_id_portability(
        self,
        *,
        resource_type: str,
        bootstrap_collection: str,
        public_list_method: str,
    ) -> IdPortabilityReport:
        """Validate that bootstrap IDs match IDs returned by a public API list call."""
        self.require_public_api_key(f"validate {resource_type} public API ID portability")
        bootstrap_items = getattr(self.client.bootstrap, bootstrap_collection, None) or {}
        public_method = getattr(self.client, public_list_method)
        public_items = await public_method()
        return compare_id_portability(
            resource_type=resource_type,
            bootstrap_items=bootstrap_items,
            public_items=public_items,
            raise_on_mismatch=True,
        )

    @property
    def client(self) -> ProtectApiClient:
        """Return the underlying :class:`ProtectApiClient`.

        Raises :class:`UniFiConnectionError` if not yet initialized.
        """
        if self._client is None or not self._initialized:
            failure = self._initialization_failure
            if failure is None or self._closed or self._attempt.in_progress:
                raise UniFiConnectionError(self._not_connected_message())
            # The same guidance, typed by the failure's category (auth, permission, timeout) and status.
            error = type(failure)(self._not_connected_message())
            error.status = failure.status
            raise error from None
        return self._client

    @property
    def is_connected(self) -> bool:
        """Return ``True`` if the client is initialized and authenticated."""
        if not self._initialized or self._client is None:
            return False
        try:
            return self._client.is_authenticated()
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Websocket
    # ------------------------------------------------------------------

    async def start_websocket(
        self,
        callback: Callable[[WSSubscriptionMessage], Any] | None = None,
    ) -> None:
        """Start the pyunifiprotect websocket subscription for real-time events.

        Parameters
        ----------
        callback:
            Optional callback invoked for every websocket message.  If ``None``,
            a default no-op logger is used.
        """
        if self._client is None:
            raise UniFiConnectionError("Cannot start websocket — client not initialized.")

        def _default_callback(msg: WSSubscriptionMessage) -> None:
            logger.debug("[protect-ws] %s", msg)

        self._ws_unsub = self._client.subscribe_websocket(callback or _default_callback)
        logger.info("[protect-cm] Websocket subscription started.")
