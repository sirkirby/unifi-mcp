"""Connection management for UniFi Protect.

Handles authentication and communication with the UniFi Protect controller
via the ``uiprotect`` (pyunifiprotect) library.  This is a thin wrapper that
owns the :class:`ProtectApiClient` lifecycle: creation, initial data fetch,
websocket subscription, and graceful shutdown.
"""

from __future__ import annotations

import logging
from typing import Any, Callable

import aiohttp
from uiprotect import ProtectApiClient
from uiprotect.data import WSSubscriptionMessage

from unifi_core.exceptions import UniFiConnectionError
from unifi_core.retry import RetryPolicy, retry_with_backoff

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
            self._client = ProtectApiClient(
                host=self.host,
                port=self.port,
                username=self.username,
                password=self.password,
                api_key=self._api_key,
                verify_ssl=self.verify_ssl,
            )
            # update() authenticates + fetches the full bootstrap (NVR, cameras, etc.)
            await self._client.update()

        try:
            await retry_with_backoff(_connect, policy=policy)
            self._initialized = True
            logger.info(
                "[protect-cm] Connected to UniFi Protect at %s:%s",
                self.host,
                self.port,
            )
            return True
        except Exception as exc:
            logger.error(
                "[protect-cm] Failed to connect to UniFi Protect at %s:%s: %s",
                self.host,
                self.port,
                exc,
                exc_info=True,
            )
            self._initialized = False
            return False

    async def close(self) -> None:
        """Gracefully shut down websocket, client session, and API session."""
        if self._ws_unsub is not None:
            try:
                self._ws_unsub()
            except Exception:
                logger.debug("[protect-cm] Error unsubscribing websocket", exc_info=True)
            self._ws_unsub = None

        if self._client is not None:
            try:
                await self._client.async_disconnect_ws()
            except Exception:
                logger.debug("[protect-cm] Error disconnecting websocket", exc_info=True)
            try:
                await self._client.close_session()
            except Exception:
                logger.debug("[protect-cm] Error closing client session", exc_info=True)
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
