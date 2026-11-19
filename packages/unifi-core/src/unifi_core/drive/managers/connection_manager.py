"""Session client for the UniFi Drive application on a UniFi OS console.

The console is logged in to with its local account (``POST /api/auth/login``),
which sets a ``TOKEN`` cookie and returns an ``x-csrf-token`` header. Every
later request sends that token, and a response carrying
``x-updated-csrf-token`` replaces it.

Rules the rest of the package relies on:

* No request at construction or startup. The first call logs in.
* An expired session (HTTP 401) is logged in again once and the request is
  sent once more. A rejected login pauses further logins on an escalating
  cool-down, so repeated tool calls cannot lock the account out.
* Redirects are not followed and proxy settings from the environment are
  ignored.
* Error text never contains the console's address, the credentials or a
  transport exception's text: messages are built from fixed text, the method,
  the request path, the HTTP status and a length-capped upstream message.
"""

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

import aiohttp
from yarl import URL

from unifi_core.exceptions import (
    UniFiAuthError,
    UniFiConnectionError,
    UniFiNotFoundError,
    UniFiOperationError,
    UniFiPermissionError,
    UniFiRateLimitError,
    UniFiValidationError,
)
from unifi_core.redaction import strip_url_origins
from unifi_core.request_paths import is_safe_request_path
from unifi_core.tls import CertificateVerificationError, certificate_safe_middleware, ssl_setting

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0

#: Root of the Drive application's API on the console.
DRIVE_API_V1 = "/proxy/drive/api/v1"
DRIVE_API_V2 = "/proxy/drive/api/v2"

_LOGIN_PATH = "/api/auth/login"
_LOGOUT_PATH = "/api/auth/logout"

# A rejected login blocks further logins for the base interval, doubling per
# consecutive rejection up to the cap.
_LOGIN_BLOCK_BASE_SECONDS = 60.0
_LOGIN_BLOCK_MAX_SECONDS = 900.0

_UPSTREAM_MESSAGE_LIMIT = 200

_FORBIDDEN_HINT = (
    "The account lacks permission for this operation; reads need a UniFi OS account with access to "
    "UniFi Drive, and changes to file services need an administrator of UniFi Drive."
)


class DriveConnectionManager:
    """Sends authenticated requests to one UniFi Drive console.

    Parameters
    ----------
    host:
        IP or hostname of the UniFi OS console running UniFi Drive (the UNAS).
    username, password:
        A local UniFi OS account on that console.
    port:
        HTTPS port of the console (default 443).
    verify_ssl:
        Verify the console's certificate against the system CAs.
    ssl_fingerprint:
        SHA-256 fingerprint of the console certificate. When set it pins the
        connection and takes precedence over ``verify_ssl``.
    tls_env_prefix:
        Server-specific prefix that a certificate error's remediation names,
        e.g. ``"DRIVE"``. Leave unset for a consumer that does not read the
        ``UNIFI_*`` variables.
    base_url:
        Overrides the ``https://host:port`` origin. For tests.
    """

    def __init__(
        self,
        host: str,
        username: str,
        password: str,
        *,
        port: int = 443,
        verify_ssl: bool = False,
        ssl_fingerprint: str | None = None,
        tls_env_prefix: str | None = None,
        timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
        base_url: str | None = None,
    ) -> None:
        self.host = host.strip() if isinstance(host, str) else ""
        self.username = username or ""
        self.password = password or ""
        self.port = int(port)
        self.tls_env_prefix = tls_env_prefix
        # A malformed pin fails here, not on the first request.
        self._ssl = ssl_setting(verify_ssl, ssl_fingerprint)
        self._timeout = aiohttp.ClientTimeout(total=timeout_seconds if timeout_seconds > 0 else DEFAULT_TIMEOUT_SECONDS)
        self._base_url = (base_url or self._origin()).rstrip("/")
        self._session: aiohttp.ClientSession | None = None
        self._csrf_token = ""
        self._logged_in = False
        self._lock = asyncio.Lock()
        self._login_block_until = 0.0
        self._login_block_count = 0
        self._last_error: str | None = None

    # ------------------------------------------------------------------
    # State
    # ------------------------------------------------------------------

    @property
    def configured(self) -> bool:
        """Whether a host, username and password are set. Says nothing about whether they work."""
        return bool(self.host and self.username and self.password)

    @property
    def is_connected(self) -> bool:
        """Whether a login succeeded and its session has not been dropped."""
        return self._logged_in and self._session is not None and not self._session.closed

    @property
    def last_connection_error(self) -> str | None:
        """Why the last login failed, or ``None`` after a success."""
        return self._last_error

    def support_status(self) -> dict[str, Any]:
        """Local connection facts with no address or credential in them."""
        return {
            "configured": self.configured,
            "connected": self.is_connected,
            "tls_verification_enabled": self._ssl is not False,
            "login_paused_seconds": round(self._login_block_remaining()),
        }

    def _origin(self) -> str:
        if not self.host:
            return "https://unconfigured.invalid"
        host = self.host
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        return f"https://{host}:{self.port}"

    # ------------------------------------------------------------------
    # Public request helpers
    # ------------------------------------------------------------------

    async def get(self, path: str, *, resource: tuple[str, str] | None = None) -> Any:
        """GET ``path``; ``resource`` names what a 404 refers to, as ``(type, id)``."""
        return await self.request("GET", path, resource=resource)

    async def put(self, path: str, json_body: Any, *, resource: tuple[str, str] | None = None) -> Any:
        return await self.request("PUT", path, json_body=json_body, resource=resource)

    async def post(self, path: str, json_body: Any, *, resource: tuple[str, str] | None = None) -> Any:
        return await self.request("POST", path, json_body=json_body, resource=resource)

    async def request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        resource: tuple[str, str] | None = None,
    ) -> Any:
        """Send one request and return its decoded body, unwrapped from Drive's envelope.

        Drive's v1 endpoints answer ``{"err": null, "type": "single", "data": {...}}``;
        ``data`` is returned. v2 endpoints and ``/api/system`` answer the object itself.
        """
        if not self.configured:
            raise UniFiAuthError(
                "UniFi Drive is not configured. Set UNIFI_DRIVE_HOST, UNIFI_DRIVE_USERNAME and UNIFI_DRIVE_PASSWORD."
            )
        url = self._url(path)
        await self._ensure_logged_in()
        token_before = self._csrf_token
        status, headers, payload = await self._send(method, path, url, json_body)
        if status == 401:
            async with self._lock:
                if self._csrf_token == token_before:
                    logger.info("[drive-cm] Session expired; logging in again.")
                    self._logged_in = False
                    await self._login()
            status, headers, payload = await self._send(method, path, url, json_body)
            if status == 401:
                self._logged_in = False
                raise UniFiAuthError(
                    f"UniFi Drive rejected {method} {path} after logging in again (401). "
                    "Check the account's access to UniFi Drive."
                )
        updated = headers.get("x-updated-csrf-token")
        if updated:
            self._csrf_token = updated
        return self._interpret(method, path, status, payload, resource)

    # ------------------------------------------------------------------
    # Session
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Log out when logged in and close the session. Never raises."""
        session, self._session = self._session, None
        was_logged_in, self._logged_in = self._logged_in, False
        if session is None or session.closed:
            return
        if was_logged_in:
            try:
                async with session.post(
                    self._url(_LOGOUT_PATH), headers={"X-CSRF-Token": self._csrf_token}, allow_redirects=False
                ):
                    pass
            except Exception as exc:  # best effort: the session is closed regardless
                logger.debug("[drive-cm] Logout failed: %s", type(exc).__name__)
        await session.close()
        self._csrf_token = ""

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=self._ssl),
                cookie_jar=aiohttp.CookieJar(unsafe=True),
                timeout=self._timeout,
                trust_env=False,
                middlewares=(certificate_safe_middleware(env_prefix=self.tls_env_prefix),),
            )
        return self._session

    async def _ensure_logged_in(self) -> None:
        if self.is_connected:
            return
        async with self._lock:
            if self.is_connected:
                return
            await self._login()

    async def _login(self) -> None:
        """Log in and store the CSRF token. Caller holds ``self._lock``."""
        remaining = self._login_block_remaining()
        if remaining > 0:
            raise UniFiAuthError(
                f"{self._last_error or 'UniFi Drive rejected the configured credentials.'} "
                f"Login attempts are paused for {remaining:.0f}s."
            )
        body = {"username": self.username, "password": self.password, "rememberMe": False}
        try:
            status, headers, _ = await self._send("POST", _LOGIN_PATH, self._url(_LOGIN_PATH), body, csrf=False)
        except UniFiConnectionError as exc:
            self._last_error = str(exc)
            raise
        if status == 200:
            self._csrf_token = headers.get("x-updated-csrf-token") or headers.get("x-csrf-token") or ""
            self._logged_in = True
            self._last_error = None
            self._login_block_count = 0
            self._login_block_until = 0.0
            logger.info("[drive-cm] Logged in to UniFi Drive.")
            return
        self._logged_in = False
        if status in (401, 403):
            self._last_error = (
                f"UniFi Drive rejected the configured username/password (HTTP {status}). "
                "Use a local UniFi OS account on the NAS, not a UI.com account with MFA."
            )
            self._block_logins()
            raise UniFiAuthError(self._last_error)
        if status == 429:
            self._last_error = "UniFi Drive is rate-limiting logins (HTTP 429)."
            self._block_logins()
            raise UniFiRateLimitError(self._last_error)
        self._last_error = f"UniFi Drive login failed (HTTP {status}). Check that the host is a UniFi OS console."
        raise UniFiConnectionError(self._last_error)

    def _block_logins(self) -> None:
        self._login_block_count += 1
        cooldown = min(_LOGIN_BLOCK_BASE_SECONDS * (2 ** (self._login_block_count - 1)), _LOGIN_BLOCK_MAX_SECONDS)
        self._login_block_until = time.monotonic() + cooldown
        logger.error("[drive-cm] Login rejected; the next attempt is allowed in %.0f seconds.", cooldown)

    def _login_block_remaining(self) -> float:
        return max(0.0, self._login_block_until - time.monotonic())

    # ------------------------------------------------------------------
    # Transport
    # ------------------------------------------------------------------

    def _url(self, path: str) -> URL:
        """Join ``path`` to the console origin, refusing a path that would change the destination."""
        if not isinstance(path, str) or not path.startswith("/") or path.startswith("//"):
            raise UniFiValidationError("UniFi Drive request path must be root-relative")
        if not is_safe_request_path(path):
            raise UniFiValidationError("Invalid UniFi Drive request path")
        url = URL(self._base_url + path, encoded=True)
        if url.origin() != URL(self._base_url).origin():
            raise UniFiValidationError("UniFi Drive request path must be root-relative")
        return url

    async def _send(
        self,
        method: str,
        path: str,
        url: URL,
        json_body: Any,
        *,
        csrf: bool = True,
    ) -> tuple[int, Any, Any]:
        """Send one request and return ``(status, headers, decoded JSON or None)``."""
        headers = {"Accept": "application/json"}
        if csrf and self._csrf_token:
            headers["X-CSRF-Token"] = self._csrf_token
        try:
            async with self._get_session().request(
                method, url, headers=headers, json=json_body, allow_redirects=False
            ) as response:
                try:
                    payload = await response.json(content_type=None)
                except (ValueError, aiohttp.ClientError):
                    payload = None
                return response.status, response.headers, payload
        except CertificateVerificationError:
            # Fixed remediation text, built by the session middleware.
            raise
        except asyncio.TimeoutError:
            failure = "timed out"
        except (aiohttp.ClientError, OSError) as exc:
            # Class only: the exception text names the console's address.
            failure = f"failed ({type(exc).__name__})"
        logger.warning("[drive-cm] %s %s %s", method, path, failure)
        raise UniFiConnectionError(
            f"UniFi Drive request {method} {path} {failure}. Check that the configured host is reachable."
        ) from None

    def _upstream_message(self, payload: Any) -> str | None:
        """Drive's own error text (``err.msg``), host-stripped and length-capped."""
        err = payload.get("err") if isinstance(payload, dict) else None
        message: Any = None
        if isinstance(err, dict):
            message = err.get("msg") or err.get("message") or err.get("code")
        elif isinstance(err, str):
            message = err
        elif isinstance(payload, dict):
            message = payload.get("message") or payload.get("msg")
        if not isinstance(message, str) or not message:
            return None
        return strip_url_origins(message, (self.host,) if self.host else ())[:_UPSTREAM_MESSAGE_LIMIT]

    def _interpret(self, method: str, path: str, status: int, payload: Any, resource: tuple[str, str] | None) -> Any:
        message = self._upstream_message(payload)
        detail = f": {message}" if message else ""
        if 200 <= status < 300:
            if isinstance(payload, dict) and "err" in payload:
                if payload.get("err"):
                    raise UniFiOperationError(f"UniFi Drive reported an error for {method} {path}{detail}")
                return payload.get("data")
            return payload
        if 300 <= status < 400:
            raise UniFiConnectionError(
                f"UniFi Drive answered {method} {path} with a redirect ({status}); not followed."
            )
        if status == 403:
            raise UniFiPermissionError(f"UniFi Drive refused {method} {path} (403). {_FORBIDDEN_HINT}")
        if status == 404 and resource is not None:
            raise UniFiNotFoundError(resource[0], resource[1])
        if status == 404:
            raise UniFiOperationError(
                f"UniFi Drive has no endpoint {method} {path} (404). Check that the host runs UniFi Drive "
                "and that its firmware is current."
            )
        if status in (400, 409, 422):
            raise UniFiValidationError(f"UniFi Drive rejected {method} {path} ({status}){detail}")
        if status == 429:
            raise UniFiRateLimitError(f"UniFi Drive is rate-limiting requests ({method} {path}).")
        raise UniFiOperationError(f"UniFi Drive API error ({status}) for {method} {path}{detail}")


def drive_path(version: int, *segments: str) -> str:
    """A path under the Drive API root, e.g. ``drive_path(1, "services", "nfs", "settings")``."""
    root = DRIVE_API_V1 if version == 1 else DRIVE_API_V2
    return "/".join((root, *segments))
