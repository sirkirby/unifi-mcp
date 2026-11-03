"""TLS settings shared by the Network, Protect and Access connection managers.

A controller connection is in one of three TLS states:

* **verified** -- the certificate must chain to a trusted CA and match the host.
* **pinned** -- the leaf certificate's SHA-256 fingerprint must equal a configured
  value. CA chain and hostname are not checked, so a self-signed console keeps a
  real identity check without a CA.
* **disabled** -- no certificate check at all. Anyone on the path can present a
  certificate and read the session credentials.

:func:`ssl_setting` turns the configuration into the value aiohttp takes for
both ``TCPConnector(ssl=...)`` and per-request ``ssl=...``, so every request a
manager sends, including the unauthenticated pre-login probes, gets the same
check.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any

import aiohttp

from unifi_core.exceptions import UniFiConnectionError

#: What aiohttp accepts as ``ssl=``: ``True`` verifies, ``False`` disables,
#: a :class:`aiohttp.Fingerprint` pins.
SslSetting = aiohttp.Fingerprint | bool

_HEX_DIGEST = re.compile(r"[0-9a-f]{64}")


def parse_fingerprint(value: str | None) -> bytes | None:
    """Parse a SHA-256 certificate fingerprint, or return ``None`` when unset.

    Accepts 64 hex digits in either case, optionally separated by colons or
    spaces, and tolerates the ``sha256 Fingerprint=`` prefix that
    ``openssl x509 -fingerprint -sha256`` prints.

    Raises:
        ValueError: The value is set but is not a SHA-256 fingerprint. The
            message never echoes the value.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    if "=" in text:
        text = text.split("=", 1)[1]
    digest = re.sub(r"[\s:]", "", text).lower()
    if not _HEX_DIGEST.fullmatch(digest):
        raise ValueError(
            "SSL fingerprint must be the SHA-256 fingerprint of the controller certificate: "
            "64 hex digits, optionally colon-separated."
        )
    return bytes.fromhex(digest)


@functools.cache
def _pin(digest: bytes) -> aiohttp.Fingerprint:
    """One ``Fingerprint`` per digest: aiohttp's connection pool keys on the object's identity.

    Never evicts: a replaced object would change the pool key of a session still
    using the pin. Digests only come from configuration, so the cache stays small.
    """
    return aiohttp.Fingerprint(digest)


def ssl_setting(verify_ssl: bool, fingerprint: str | None = None) -> SslSetting:
    """Return the aiohttp ``ssl=`` value for a controller connection.

    A configured fingerprint wins over ``verify_ssl``: pinning is a stricter
    check than nothing and a different one from CA verification, and a console
    with a self-signed certificate can only use the pin.
    """
    digest = parse_fingerprint(fingerprint)
    if digest is not None:
        return _pin(digest)
    return bool(verify_ssl)


def tls_mode(setting: SslSetting) -> str:
    """Name the TLS state of ``setting``: ``verified``, ``pinned`` or ``disabled``."""
    if isinstance(setting, aiohttp.Fingerprint):
        return "pinned"
    return "verified" if setting else "disabled"


def warn_if_unverified(logger: logging.Logger, setting: SslSetting, *, product: str, env_prefix: str) -> None:
    """Log one startup warning when certificate checks are disabled.

    Args:
        logger: The product logger.
        setting: The value from :func:`ssl_setting`.
        product: Display name, e.g. ``"Network"``.
        env_prefix: Server-specific env prefix, e.g. ``"NETWORK"``.
    """
    if setting is not False:
        return
    logger.warning(
        "TLS verification is off for the UniFi %s connection, so the controller's identity is not checked. "
        "To check it, set UNIFI_SSL_FINGERPRINT or UNIFI_%s_SSL_FINGERPRINT to its certificate's SHA-256 fingerprint.",
        product,
        env_prefix,
    )


def server_ssl_setting(
    logger: logging.Logger, verify_ssl: bool, fingerprint: str | None, *, product: str, env_prefix: str
) -> SslSetting:
    """Resolve an MCP server's TLS settings at startup.

    Warns once when nothing checks the controller, and exits on a malformed pin
    rather than starting with a check the operator did not get. Only for a server
    reading the ``UNIFI_*`` variables: a library consumer calls :func:`ssl_setting`.

    Raises:
        SystemExit: The fingerprint is malformed. The log line never echoes it.
    """
    try:
        setting = ssl_setting(verify_ssl, fingerprint)
    except ValueError as error:
        logger.critical("Invalid UNIFI_SSL_FINGERPRINT or UNIFI_%s_SSL_FINGERPRINT: %s", env_prefix, error)
        raise SystemExit(2) from None
    warn_if_unverified(logger, setting, product=product, env_prefix=env_prefix)
    return setting


class CertificateVerificationError(UniFiConnectionError):
    """A controller request failed its certificate check.

    Carries fixed remediation text and the failing exception's class only. The
    aiohttp exception it replaces names the controller host and port, and a pin
    mismatch also both fingerprints; build it with :func:`certificate_failure`
    and raise it ``from None`` outside the ``except`` block, so neither the original
    nor an exception a caller is handling renders with it.
    """


def is_certificate_error(error: BaseException) -> bool:
    """Whether ``error``, or anything it was raised from, is a failed certificate check.

    Walks ``__context__`` as well as ``__cause__``: aiounifi re-raises transport
    failures as ``RequestError(...) from None``, which hides the cause but keeps
    the context.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(
            current,
            (aiohttp.ClientConnectorCertificateError, aiohttp.ServerFingerprintMismatch, CertificateVerificationError),
        ):
            return True
        current = current.__cause__ or current.__context__
    return False


def certificate_error_hint(*, env_prefix: str | None = None, pin_variable: str | None = None) -> str:
    """Fixed remediation text for a failed certificate check. Never quotes the certificate.

    Names the ``UNIFI_*`` settings only when ``env_prefix`` says the caller reads
    them; another consumer of these managers, such as the API server, does not.
    ``pin_variable`` names the setting that pins this path, when it isn't the
    server's usual one.
    """
    if env_prefix is None:
        return (
            "The controller's TLS certificate failed verification. Check the certificate on the controller "
            "and this connection's TLS settings; if a fingerprint is pinned, the certificate has changed."
        )
    pin = pin_variable or f"UNIFI_{env_prefix}_SSL_FINGERPRINT (or UNIFI_SSL_FINGERPRINT)"
    return (
        "The controller's TLS certificate failed verification. For a self-signed console certificate, "
        f"set {pin} to its SHA-256 fingerprint. "
        "If a fingerprint is already set, the certificate has changed: confirm the change is expected, "
        "then update the fingerprint. To turn the check off instead, clear any fingerprint and set "
        f"UNIFI_{env_prefix}_VERIFY_SSL=false."
    )


def certificate_failure(
    error: BaseException, *, env_prefix: str | None = None, pin_variable: str | None = None
) -> CertificateVerificationError:
    """Replace a failed certificate check with an error that is safe to log and return to a caller.

    The message is the exception class plus :func:`certificate_error_hint`; nothing from
    ``str(error)`` is kept.
    """
    hint = certificate_error_hint(env_prefix=env_prefix, pin_variable=pin_variable)
    return CertificateVerificationError(f"{type(error).__name__}: {hint}")


def safe_error_text(error: BaseException, *, env_prefix: str | None = None) -> Any:
    """``error`` itself, or the fixed certificate text when it is a failed certificate check.

    For log calls that format an exception whose text is otherwise safe to
    record; a certificate failure names the controller and both fingerprints.
    """
    if is_certificate_error(error) and not isinstance(error, CertificateVerificationError):
        return certificate_failure(error, env_prefix=env_prefix)
    return error


def certificate_safe_middleware(
    *, env_prefix: str | None = None, pin_variable: str | None = None
) -> aiohttp.ClientMiddlewareType:
    """Session middleware that replaces a failed certificate check with :class:`CertificateVerificationError`.

    Installed on every controller session so the translation happens below the
    SDKs. aiounifi, uiprotect and py-unifi-access each wrap an aiohttp
    ``ClientError`` in their own exception with the controller URL and the raw
    error in its text. :class:`CertificateVerificationError` is not a
    ``ClientError``, so it passes through them unwrapped, and it is raised
    ``from None`` outside the ``except`` block, so no traceback renders the original.
    """

    async def middleware(request: aiohttp.ClientRequest, handler: aiohttp.ClientHandlerType) -> aiohttp.ClientResponse:
        failure: CertificateVerificationError | None = None
        try:
            return await handler(request)
        except (aiohttp.ClientConnectorCertificateError, aiohttp.ServerFingerprintMismatch) as error:
            failure = certificate_failure(error, env_prefix=env_prefix, pin_variable=pin_variable)
        raise failure from None

    return middleware
