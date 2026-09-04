"""Connection management for UniFi Access.

Handles authentication and communication with the UniFi Access controller
via two independent auth paths:

1. **API key path** -- uses ``py-unifi-access`` (``UnifiAccessApiClient``) on the
   dedicated Access API port (default 12445).
2. **Proxy session path** -- logs in via ``/api/auth/login`` on the UniFi OS
   Console (port 443) and proxies requests through
   ``/proxy/access/api/v2/...`` with cookie + CSRF token.

At least one path must succeed during :meth:`initialize`.  When both are
available the caller can choose which path to use per-request (API client
is generally preferred for supported endpoints; the proxy path covers
everything else).
"""

from __future__ import annotations

import asyncio
import functools
import logging
import ssl
from typing import Any, Dict

import aiohttp

from unifi_core.exceptions import UniFiAuthError, UniFiConnectionError
from unifi_core.retry import RetryPolicy, retry_with_backoff
from unifi_core.support_bundle import (
    SafeConnectionAttempt,
    connection_attempt_failed,
    connection_attempt_not_configured,
    connection_attempt_started,
    connection_attempt_succeeded,
)

logger = logging.getLogger(__name__)


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

        Tries both paths independently.  At least one must succeed or
        :class:`UniFiConnectionError` is raised.

        Uses ``retry_with_backoff`` from :mod:`unifi_core.retry` so
        transient network errors during startup are retried.

        Returns ``True`` on success.
        """
        if self._initialized and (self._api_client_available or self._proxy_available):
            return True

        policy = RetryPolicy(
            max_retries=3,
            base_delay=2.0,
            max_delay=30.0,
            retryable_exceptions=(Exception,),
        )

        async def _connect() -> None:
            await self._try_api_client()
            await self._try_proxy_session()

            if not self._api_client_available and not self._proxy_available:
                raise UniFiConnectionError(
                    f"Failed to establish any auth path to UniFi Access at {self.host}. "
                    "Ensure either an API key or username/password credentials are configured."
                )

        self._support_attempt = connection_attempt_started()
        try:
            await retry_with_backoff(_connect, policy=policy)
            self._initialized = True
            self._support_attempt = connection_attempt_succeeded()
            logger.info(
                "[access-cm] Connected to UniFi Access at %s (api_client=%s, proxy=%s)",
                self.host,
                self._api_client_available,
                self._proxy_available,
            )
            return True
        except Exception as exc:
            self._support_attempt = connection_attempt_failed(exc)
            logger.error(
                "[access-cm] Failed to connect to UniFi Access at %s: %s",
                self.host,
                exc,
                exc_info=True,
            )
            self._initialized = False
            raise

    async def _try_api_client(self) -> None:
        """Attempt to initialise the py-unifi-access API client."""
        if not self._api_key:
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
                raise UniFiAuthError(f"Proxy login failed: HTTP {resp.status}{(' — ' + body[:200]) if body else ''}")
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
            raise UniFiConnectionError("Proxy session is not available. Call initialize() first.")

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
            raise UniFiConnectionError("Proxy session is not available. Call initialize() first.")

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
            raise UniFiConnectionError("Proxy session is not available. Call initialize() first.")

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
        """Gracefully shut down both sessions."""
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
