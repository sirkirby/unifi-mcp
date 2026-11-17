"""Deterministic response redaction for UniFi controller payloads."""

from __future__ import annotations

import functools
import inspect
import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from typing import Any
from urllib.parse import quote

REDACTED = "***REDACTED***"

_SENSITIVE_SEGMENTS = frozenset(
    {
        "password",
        "passwd",
        "passphrase",
        "psk",
        "secret",
        "token",
        "authorization",
        "cookie",
    }
)

_SENSITIVE_EXACT = frozenset(
    {
        "auth",
        "x_password",
        "x_passphrase",
        "api_key",
        # The request header that carries an API key.
        "x_api_key",
        "api_token",
        "private_key",
        "privatekey",
        "private_preshared_keys",
        "privatepresharedkeys",
        "wireguard_private_key",
        "wireguardprivatekey",
        "preshared_key",
        "presharedkey",
        "auth_key",
        "authkey",
        "x_iapp_key",
        "x_mgmt_key",
        # Controller device credentials and built-in OpenVPN private keys.
        "x_authkey",
        "x_auth_key",
        "x_inform_authkey",
        "x_vwirekey",
        "syslog_key",
        "x_ca_key",
        "x_server_key",
        "x_shared_client_key",
        "xiappkey",
        "community",
        "snmp_community",
        "snmpcommunity",
        "tls_auth",
        "tlsauth",
        "tls_crypt",
        "tlscrypt",
        "pin_code",
        "pincode",
        "rtsp_alias",
        "rtsp_url",
        "rtsps_url",
        "rtsps_streams",
        # VPN config blobs: the secret rides inside the value (e.g. a WireGuard
        # .conf with `PrivateKey =`, or an OpenVPN .ovpn with an embedded
        # tls-crypt static key). Key-name matching can't see into the value, so
        # the whole blob field is treated as a secret (suppression).
        "openvpn_configuration",
        "wireguard_client_configuration_file",
        "wireguard_server_configuration_file",
    }
)

# Words that name secret key material only when immediately followed by "key".
# Requiring the pair keeps role-infixed controller fields such as
# ``wireguard_client_private_key`` sensitive while leaving non-secret keys like
# ``public_key`` and ``network_key`` visible.
_SENSITIVE_KEY_QUALIFIERS = frozenset({"private", "preshared"})

_SENSITIVE_COMPOUNDS = frozenset(
    {
        "xpassphrase",
        "apikey",
        "apitoken",
        "privatekey",
        "privatepresharedkeys",
        "wireguardprivatekey",
        "presharedkey",
        "authkey",
        "xiappkey",
        "xmgmtkey",
        "xauthkey",
        "xinformauthkey",
        "xvwirekey",
        "syslogkey",
        "xcakey",
        "xserverkey",
        "xsharedclientkey",
        "snmpcommunity",
        "tlsauth",
        "tlscrypt",
        "pincode",
        "rtspalias",
        "rtspurl",
        "rtspsurl",
        "rtspsstreams",
    }
)


def _segments(key: str) -> list[str]:
    camel_split = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key)
    return [part for part in re.split(r"[^A-Za-z0-9]+", camel_split.lower()) if part]


def _is_secret_entry(key: Any, value: Any) -> bool:
    """Whether a mapping entry carries secret material to hide.

    A boolean is state, never secret material: ``x_ssh_auth_password_enabled``
    says whether password login is on and ``ssh_password_hash_set`` whether a
    hash is stored; the secrets live in other keys. Only the value decision is
    relaxed: the key stays sensitive for :func:`is_sensitive_key`, so the
    write-back guard is unchanged, and a string under such a key is still
    hidden. ``None`` is left alone so an absent field stays visibly absent.
    """
    return value is not None and not isinstance(value, bool) and is_sensitive_key(key)


def is_sensitive_key(key: Any) -> bool:
    """Return true when a mapping key conventionally carries secret material."""
    if not isinstance(key, str) or not key:
        return False
    parts = _segments(key)
    if not parts:
        return False
    normalized = "_".join(parts)
    compound = "".join(parts)
    if normalized in _SENSITIVE_EXACT or compound in _SENSITIVE_EXACT:
        return True
    if compound in _SENSITIVE_COMPOUNDS:
        return True
    for index, part in enumerate(parts):
        if part.endswith("passwd") and part != "passwd":
            # Hash-prefixed spellings: sha512passwd, md5passwd, bcryptpasswd.
            return True
        if part not in _SENSITIVE_SEGMENTS:
            continue
        if part == "token" and index + 1 < len(parts) and parts[index + 1] in {"count", "counts"}:
            continue
        return True
    for left, right in zip(parts, parts[1:]):
        if right == "key" and left in _SENSITIVE_KEY_QUALIFIERS:
            return True
    # "preshared" sometimes arrives underscore-split as "pre_shared" (e.g. the
    # controller's x_ipsec_pre_shared_key field) — match that 3-gram too.
    for first, second, third in zip(parts, parts[1:], parts[2:]):
        if (first, second, third) == ("pre", "shared", "key"):
            return True
    return False


def redact_value(
    key: Any,
    value: Any,
    *,
    redact_sensitive: bool = True,
    marker: str = REDACTED,
) -> Any:
    """Redact a single ``key``/``value`` pair by the shared vocabulary.

    Returns ``marker`` when ``key`` names secret material and ``value`` is
    present; otherwise returns ``value`` unchanged. Use at boundaries that
    project individual fields (e.g. typed serializers) so the sensitivity
    decision stays routed through :func:`is_sensitive_key` rather than a
    local hard-coded field list.
    """
    if not redact_sensitive:
        return value
    return marker if _is_secret_entry(key, value) else value


def redact_sensitive_fields(
    obj: Any,
    *,
    redact_sensitive: bool = True,
    marker: str = REDACTED,
) -> Any:
    """Return a redacted copy of ``obj``."""
    if not redact_sensitive:
        return obj
    if isinstance(obj, Mapping):
        return {
            key: marker
            if _is_secret_entry(key, value)
            else redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker)
            for key, value in obj.items()
        }
    if isinstance(obj, tuple):
        return tuple(redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker) for value in obj)
    if isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        return [redact_sensitive_fields(value, redact_sensitive=redact_sensitive, marker=marker) for value in obj]
    return obj


def redaction_marker_paths(obj: Any, *, marker: str = REDACTED, prefix: str = "") -> list[str]:
    """Return sensitive-key paths whose value is the redaction marker."""
    paths: list[str] = []
    if isinstance(obj, Mapping):
        for key, value in obj.items():
            key_text = str(key)
            path = f"{prefix}.{key_text}" if prefix else key_text
            if value == marker and is_sensitive_key(key_text):
                paths.append(path)
            paths.extend(redaction_marker_paths(value, marker=marker, prefix=path))
    elif isinstance(obj, Sequence) and not isinstance(obj, (str, bytes, bytearray)):
        for index, value in enumerate(obj):
            path = f"{prefix}[{index}]" if prefix else f"[{index}]"
            paths.extend(redaction_marker_paths(value, marker=marker, prefix=path))
    return paths


# ---------------------------------------------------------------------------
# Value scrubbing for error paths
#
# Key-based redaction only helps when the secret still sits under its key. A
# controller error that quotes the request, or a transport error that quotes
# the login, carries the value inside free text. These helpers scrub known
# secret *values* out of text and out of exceptions before they are logged,
# rethrown or written to an audit sink.
# ---------------------------------------------------------------------------

# Values shorter than this are only scrubbed on token boundaries so a short
# secret such as "12" does not shred every number in the message.
_BOUNDARY_SCRUB_MAX_LEN = 4

# Message-bearing attributes that ``str(exc)`` may read instead of ``args``
# (aiohttp ``ClientResponseError.message``, ``OSError.strerror``, ...).
_EXCEPTION_MESSAGE_ATTRS = ("message", "msg", "strerror", "reason", "detail")

# Structured attributes an exception renders from instead of ``args``.
# ``aiohttp.ClientResponseError.__str__`` reads ``request_info.real_url``, and
# the attribute is a separate reference to the same object as ``args[0]`` — so
# rewriting ``args`` alone leaves every reader of the attribute, and ``str()``
# itself, looking at the unscrubbed original.
_EXCEPTION_STRUCTURED_ATTRS = ("request_info",)


def collect_secret_values(obj: Any) -> set[str]:
    """Return the scalar values held under sensitive keys anywhere in ``obj``.

    Walks mappings and sequences. Strings are returned as-is; ints and floats
    (but not bools) are returned as their string form so a numeric PIN or
    community string can still be matched in free text.
    """
    found: set[str] = set()

    def _walk(value: Any, secret: bool) -> None:
        if isinstance(value, Mapping):
            for key, item in value.items():
                _walk(item, secret or is_sensitive_key(key))
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
            for item in value:
                _walk(item, secret)
        elif secret and isinstance(value, (str, int, float)) and not isinstance(value, bool):
            text = str(value)
            if text:
                found.add(text)

    _walk(obj, False)
    return found


# How a value can be written into a message. Each entry applies ONE policy to
# the whole value, which is what a real emitter does: ``repr`` keeps non-ASCII
# literal and escapes quotes; ``json.dumps`` escapes quotes either way and
# decides non-ASCII with ``ensure_ascii``; ``ascii`` and ``repr(bytes)`` write
# different numeric escapes; a URL carries it percent-encoded; a PHP- or
# Jackson-style encoder also escapes the forward slash.
_EMITTERS = (
    lambda value: value,
    lambda value: repr(value)[1:-1],  # strip the quotes repr puts around it
    lambda value: ascii(value)[1:-1],
    lambda value: json.dumps(value)[1:-1],  # strip the JSON quotes
    lambda value: json.dumps(value, ensure_ascii=False)[1:-1],
    lambda value: json.dumps(value)[1:-1].replace("/", "\\/"),
    lambda value: repr(value.encode())[2:-1],  # strip the b'' wrapper
    lambda value: quote(value, safe=""),
)


def _encoded_forms(secret: str) -> list[str]:
    """Every rendering of ``secret`` a message on these paths can carry, longest first.

    Closed under applying the emitters twice, because a message can be escaped
    twice: aiounifi renders an already-JSON body with ``repr(bytes)`` on its
    429 path, and a controller can echo a rejected record as a nested JSON
    string. Each form is a literal, so matching stays linear and exact — an
    alternation built per character would have to guess how many characters of
    the text one character of the secret occupies, and guessing wrong either
    misses the value or costs seconds of blocked event loop.

    What it does not cover, deliberately: a mixture no single emitter produces,
    base64, and HTML entities. None is emitted on these paths.
    """
    once = {emit(secret) for emit in _EMITTERS}
    forms = once | {emit(form) for form in once for emit in _EMITTERS}
    return sorted((form for form in forms if form), key=len, reverse=True)


def _ordered_secrets(secrets: Iterable[str] | Mapping[str, bool], boundary: bool) -> list[tuple[str, bool]]:
    """Non-empty secrets with their boundary rule, longest first.

    Longest first so a secret containing another is not left partially visible:
    masking a short login first would chop a longer submitted value and leave
    its tail beside a mask the reader can identify. A mapping gives the rule
    per value, which is what a caller holding both a word-like login and opaque
    submitted values needs from one pass.
    """
    if isinstance(secrets, Mapping):
        items = {secret: bool(rule) for secret, rule in secrets.items() if secret}
    else:
        items = {secret: boundary for secret in secrets if secret}
    return sorted(items.items(), key=lambda item: len(item[0]), reverse=True)


def _scrub_text(text: str, ordered: list[tuple[str, bool]], marker: str) -> str:
    for secret, boundary in ordered:
        # Every rendering, not just the literal: the literal may be absent from
        # the text while the value is still there, escaped.
        for form in _encoded_forms(secret):
            if form not in text:
                continue
            if boundary or len(secret) < _BOUNDARY_SCRUB_MAX_LEN:
                # A word-like secret is held to token boundaries. ``-`` and
                # ``_`` separate tokens for a login ("admin" must not match
                # inside "admin-panel" when the whole word is what was
                # configured) but not for a short opaque value, where "123" in
                # "123-foo" is the secret itself.
                edge = r"[A-Za-z0-9_-]" if boundary else r"[A-Za-z0-9]"
                text = re.sub(rf"(?<!{edge}){re.escape(form)}(?!{edge})", marker, text)
            else:
                text = text.replace(form, marker)
    return text


def _updated_copy(mapping: Mapping, values: Mapping) -> Any:
    """A mutable copy of ``mapping`` carrying ``values``, for rebuilding a proxy."""
    copied = mapping.copy()
    for key, item in values.items():
        copied[key] = item
    return copied


def _rewrite_any(value: Any, text_fn: Callable[[str], str], *, redact_keys: bool) -> Any:
    """Apply ``text_fn`` to every string inside ``value``, keeping container types.

    With ``redact_keys``, a whole value under a sensitive key becomes
    ``REDACTED`` instead: that is the marker the write-back guards
    (``redaction_marker_paths``) recognise, and a payload value carrying any
    other marker would sail past them into a controller write.
    """
    if isinstance(value, str):
        return text_fn(value)
    if isinstance(value, Mapping):
        rewritten = {
            key: (
                REDACTED
                if redact_keys and _is_secret_entry(key, item)
                else _rewrite_any(item, text_fn, redact_keys=redact_keys)
            )
            for key, item in value.items()
        }
        # Keep the mapping type: aiohttp's headers are a case-insensitive
        # multidict, and a plain dict would silently lose that. A read-only
        # proxy is rebuilt from a mutable copy of itself, which is the only
        # thing its constructor accepts.
        for rebuild in (lambda: type(value)(_updated_copy(value, rewritten)), lambda: type(value)(rewritten)):
            try:
                return rebuild()
            except Exception:  # noqa: BLE001 - any mapping we cannot rebuild degrades to a dict
                continue
        return rewritten
    if isinstance(value, tuple):
        items = [_rewrite_any(item, text_fn, redact_keys=redact_keys) for item in value]
        # aiohttp raises with a NamedTuple (``RequestInfo``) in ``args``; a bare
        # tuple rebuild would silently strip the type.
        return type(value)(*items) if hasattr(value, "_fields") else tuple(items)
    if type(value).__module__ == "yarl" or type(value).__name__ == "URL":
        # A URL renders its userinfo and query percent-encoded, and
        # ``ClientResponseError.__str__`` prints it. Rebuild from the rewritten
        # text rather than leave the object untouched.
        try:
            return type(value)(text_fn(str(value)), encoded=True)
        except Exception:
            return text_fn(str(value))
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_rewrite_any(item, text_fn, redact_keys=redact_keys) for item in value]
    if isinstance(value, (bytes, bytearray)):
        # A raw body kept as bytes is text to whoever renders it. latin-1
        # round-trips every byte, so a body that is not valid UTF-8 keeps its
        # bytes instead of being replaced away.
        rewritten_bytes = text_fn(value.decode("latin-1")).encode("latin-1", "replace")
        return bytearray(rewritten_bytes) if isinstance(value, bytearray) else rewritten_bytes
    return value


def _scrub_any(value: Any, ordered: list[tuple[str, bool]], marker: str) -> Any:
    """Scrub strings; redact mappings by key and scrub inside them; recurse into sequences.

    ``marker`` applies to free text; a whole value under a sensitive key always
    becomes ``REDACTED`` (see ``_rewrite_any``).
    """
    return _rewrite_any(value, lambda text: _scrub_text(text, ordered, marker), redact_keys=True)


def _rewrite_exception(error: BaseException, text_fn: Callable[[str], str], *, redact_keys: bool) -> BaseException:
    """Apply ``text_fn`` throughout ``error`` and its cause chain, in place.

    Rewrites ``args``, the common message attributes, the structured attributes
    an exception renders from instead of ``args``, and PEP 678 notes, then
    follows ``__cause__``/``__context__``.
    """
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        current.args = tuple(_rewrite_any(arg, text_fn, redact_keys=redact_keys) for arg in current.args)
        for attr in _EXCEPTION_MESSAGE_ATTRS:
            value = getattr(current, attr, None)
            if isinstance(value, str):
                try:
                    setattr(current, attr, text_fn(value))
                except (AttributeError, TypeError):
                    pass  # read-only property; ``args`` above already carries the rewritten text
        for attr in _EXCEPTION_STRUCTURED_ATTRS:
            value = getattr(current, attr, None)
            if value is not None:
                try:
                    setattr(current, attr, _rewrite_any(value, text_fn, redact_keys=redact_keys))
                except (AttributeError, TypeError):
                    pass  # read-only attribute
        notes = getattr(current, "__notes__", None)
        if isinstance(notes, list):
            current.__notes__ = [_rewrite_any(note, text_fn, redact_keys=redact_keys) for note in notes]
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return error


def scrub_secret_values(
    text: str,
    secrets: Iterable[str] | Mapping[str, bool],
    *,
    marker: str = REDACTED,
    boundary: bool = False,
) -> str:
    """Replace every occurrence of each secret value in ``text`` with ``marker``.

    Longer values are replaced first, and each value is matched however its
    characters were escaped by whoever built the text (see ``_char_forms``).
    Very short values are matched only on token boundaries (see
    ``_BOUNDARY_SCRUB_MAX_LEN``); pass ``boundary=True`` to hold every value to
    that rule, or a mapping of value to rule to mix the two in one pass, which
    is what a word-like login alongside opaque submitted values needs.
    """
    if not text:
        return text
    return _scrub_text(text, _ordered_secrets(secrets, boundary), marker)


def sanitize_exception(
    error: BaseException,
    secrets: Iterable[str] | Mapping[str, bool],
    *,
    marker: str = REDACTED,
    boundary: bool = False,
) -> BaseException:
    """Scrub secret values out of ``error`` in place and return it.

    Rewrites ``args`` (strings are scrubbed; aiounifi raises with the decoded
    response *dict* as ``args[0]``, which is redacted by key and scrubbed
    inside), the common message attributes, the structured attributes an
    exception renders from instead of ``args``, PEP 678 notes, and follows
    ``__cause__``/``__context__`` so a wrapped transport error is cleaned too.
    Mutating in place keeps the exception type and identity, so callers that
    match on ``except ResponseError`` keep working and a later ``raise`` or
    ``str(e)`` sees the scrubbed text. Pass ``boundary=True`` for a word-like
    value such as a login, which must not be masked inside a longer word.
    """
    ordered = _ordered_secrets(secrets, boundary)
    if not ordered:
        return error
    return _rewrite_exception(error, lambda text: _scrub_text(text, ordered, marker), redact_keys=True)


# The origin of an absolute URL: scheme, any userinfo, host and port. aiounifi
# quotes the full request URL in its errors ("Call <url> received 403
# Forbidden", "Error requesting data from <url>: ...") and aiohttp renders it
# from ``request_info``. The host run admits ``<`` and ``>`` so userinfo that
# a credential pass already masked (``https://<mask>:<mask>@host``) goes with
# the origin.
_URL_ORIGIN_RE = re.compile(r"\b(?:https?|wss?)://[^/\s'\"?#]+", re.IGNORECASE)

# What a removed origin or host reads as when no path follows it. It holds no
# whitespace, so a "Call <url> received <status>" message keeps its shape.
CONTROLLER_PLACEHOLDER = "<controller>"


def strip_url_origins(text: str, hosts: Iterable[str] = ()) -> str:
    """Remove every URL origin, and each of ``hosts`` written bare, from ``text``.

    ``https://host:443/proxy/network/api`` becomes ``/proxy/network/api``: the
    path says what failed, the origin only says where the controller lives. An
    origin with no path after it, and a bare host (aiohttp writes "Cannot
    connect to host <host>:<port>"), become ``CONTROLLER_PLACEHOLDER``. Hosts
    are matched case-insensitively on hostname boundaries.
    """
    if not text:
        return text
    if "://" in text:
        text = _URL_ORIGIN_RE.sub(
            lambda m: "" if m.string.startswith("/", m.end()) else CONTROLLER_PLACEHOLDER,
            text,
        )
    for host in _bare_hosts(hosts):
        if host.lower() in text.lower():
            text = re.sub(
                rf"(?<![\w.-]){re.escape(host)}(?![\w-]|\.[\w-])",
                CONTROLLER_PLACEHOLDER,
                text,
                flags=re.IGNORECASE,
            )
    return text


def _bare_hosts(hosts: Iterable[str]) -> list[str]:
    """Hostnames from configured hosts, which may carry a scheme, port or path."""
    bare: set[str] = set()
    for host in hosts:
        if not isinstance(host, str):
            continue
        value = host.strip()
        if "://" in value:
            value = value.split("://", 1)[1]
        value = value.split("/", 1)[0].rsplit("@", 1)[-1]
        if not value.startswith("[") and value.count(":") == 1:
            value = value.split(":", 1)[0]
        if value:
            bare.add(value)
    return sorted(bare, key=len, reverse=True)


def strip_exception_url_origins(error: BaseException, hosts: Iterable[str] = ()) -> BaseException:
    """Remove URL origins and ``hosts`` from ``error`` in place and return it.

    Covers the same places ``sanitize_exception`` does, cause chain included,
    and keeps the exception type and identity.
    """
    host_list = list(hosts)
    return _rewrite_exception(error, lambda text: strip_url_origins(text, host_list), redact_keys=False)


def append_exception_hint(error: BaseException, hint: str) -> BaseException:
    """Append fixed ``hint`` to ``error``'s message in place, once, and return it.

    Only a string message is extended; the exception keeps its type, its
    other arguments and its identity, so ``except`` clauses and status
    parsing that read the start of the message keep working.
    """
    message = error.args[0] if error.args else ""
    if not isinstance(message, str) or hint in message:
        return error
    head = message.rstrip().rstrip(".")
    error.args = (f"{head}. {hint}" if head else hint, *error.args[1:])
    return error


def strip_origins_from_methods(
    target: Any,
    names: Iterable[str],
    hosts: Iterable[str] = (),
    *,
    on_error: Callable[[BaseException], None] | None = None,
) -> None:
    """Wrap ``target``'s coroutine methods so what they raise carries no URL origin.

    For an SDK client whose every request passes through a few methods: each
    named coroutine method is replaced on the instance by one that strips URL
    origins and ``hosts`` from the raised exception (cause chain included),
    lets ``on_error`` annotate it, and re-raises the same object. The class,
    the identity and the traceback are kept. A missing or non-coroutine
    attribute is left alone.
    """
    host_list = list(hosts)
    for name in names:
        original = getattr(target, name, None)
        if original is None or not inspect.iscoroutinefunction(original):
            continue
        setattr(target, name, _origin_stripping(original, host_list, on_error))


def _origin_stripping(
    original: Callable[..., Any],
    hosts: list[str],
    on_error: Callable[[BaseException], None] | None,
) -> Callable[..., Any]:
    @functools.wraps(original)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return await original(*args, **kwargs)
        except Exception as error:
            strip_exception_url_origins(error, hosts)
            if on_error is not None:
                on_error(error)
            raise

    return wrapper
