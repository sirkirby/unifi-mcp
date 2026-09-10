"""Connection management for UniFi Protect.

Handles authentication and communication with the UniFi Protect controller
via the ``uiprotect`` (pyunifiprotect) library.  This is a thin wrapper that
owns the :class:`ProtectApiClient` lifecycle: creation, initial data fetch,
websocket subscription, and graceful shutdown.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable

import aiohttp
from uiprotect import ProtectApiClient
from uiprotect.data import WSSubscriptionMessage

from unifi_core.auth import AuthenticationStatus, AuthMethod
from unifi_core.exceptions import UniFiConnectionError
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
    ):
        self.host = host
        self.username = username
        self.password = password
        self.port = port
        self.site = site
        self.verify_ssl = verify_ssl
        self._api_key = api_key

        self._client: ProtectApiClient | None = None
        self._api_session: aiohttp.ClientSession | None = None
        self._ws_unsub: Callable[[], None] | None = None
        self._initialized = False
        self._support_attempt = SafeConnectionAttempt().model_dump(mode="json")

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def initialize(self) -> bool:
        """Create the :class:`ProtectApiClient`, authenticate, and fetch bootstrap data.

        Uses ``retry_with_backoff`` from :mod:`unifi_core.retry` so transient
        network errors during startup are retried with exponential back-off.

        Returns ``True`` on success, ``False`` on failure.
        """
        if self._initialized and self._client is not None:
            return True

        policy = RetryPolicy(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            retryable_exceptions=(Exception,),
        )

        async def _connect() -> None:
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
                # A failed or cancelled bootstrap must not orphan the SDK's
                # session when a later retry creates another client.
                await self._dispose_client(client)
                raise
            self._client = client

        self._support_attempt = connection_attempt_started()
        try:
            await retry_with_backoff(_connect, policy=policy)
            self._initialized = True
            self._support_attempt = connection_attempt_succeeded()
            logger.info(
                "[protect-cm] Connected to UniFi Protect at %s:%s",
                self.host,
                self.port,
            )
            return True
        except Exception as exc:
            self._support_attempt = connection_attempt_failed(exc)
            logger.error(
                "[protect-cm] Failed to connect to UniFi Protect at %s:%s: %s",
                self.host,
                self.port,
                exc,
                exc_info=True,
            )
            self._initialized = False
            return False

    @staticmethod
    async def _dispose_client(client: ProtectApiClient) -> None:
        for operation in ("async_disconnect_ws", "close_session"):
            try:
                await getattr(client, operation)()
            except Exception as exc:
                logger.debug("[protect-cm] %s failed: %s", operation, type(exc).__name__)

    async def close(self) -> None:
        """Gracefully shut down websocket, client session, and API session."""
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[protect-cm] Error unsubscribing websocket", exc_info=True)
            self._ws_unsub = None

        if self._client is not None:
            await self._dispose_client(self._client)
            self._client = None

        if self._api_session is not None and not self._api_session.closed:
            await self._api_session.close()
            self._api_session = None

        self._initialized = False
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
            raise UniFiConnectionError("ProtectConnectionManager is not initialized. Call initialize() first.")
        return self._client

    @property
    def api_session(self) -> aiohttp.ClientSession:
        """Return (or lazily create) an :class:`aiohttp.ClientSession` with the API key header.

        This session is intended for official Protect API endpoints that require
        an API key rather than cookie-based auth.
        """
        if self._api_session is None or self._api_session.closed:
            headers: dict[str, str] = {}
            if self._api_key:
                headers["X-API-Key"] = self._api_key
            self._api_session = aiohttp.ClientSession(headers=headers)
        return self._api_session

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
