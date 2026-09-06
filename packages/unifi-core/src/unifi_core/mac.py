"""MAC address normalization.

The UniFi controller reports MAC addresses in lowercase. Callers supply
whatever they have - and the form printed on a device label, quoted in
vendor documentation, or pasted out of another tool is very often
uppercase. Comparing the two with a raw ``==`` reports "not found" for
hardware that plainly exists, which reads as a broken controller rather
than a case mismatch.

Use :func:`mac_equal` for comparisons rather than normalizing both sides at
each call site: it is the guard against ``None == None`` matching a record
that has no ``mac`` field at all.

**Call pattern at an entry point**, and the trailing ``or`` is not redundant::

    client_mac = normalize_mac(client_mac) or client_mac

:func:`normalize_mac` returns ``None`` for anything unusable, and several
callers interpolate the result straight into a request path - ``f"/stat/
device/{device_mac}"``. Dropping the fallback would send the literal string
``None`` to the controller. With it, an unusable input reproduces the old
behavior exactly (the lookup misses and raises) rather than inventing a new
failure mode. Normalize once, at the entry point, and use the result for the
lookup *and* for anything sent onward - the controller reports lowercase, so
matching a record and then sending a different casing is how a fixed lookup
turns into a request the controller may still reject, later and more quietly.
"""

import re
from typing import Any, Optional

__all__ = [
    "normalize_mac",
    "mac_equal",
    "looks_like_mac",
    "normalize_mac_list",
    "canonical_mac",
    "mask_macs",
]

# Six hex pairs separated by ':' or '-', or twelve bare hex digits.
_MAC_RE = re.compile(r"^(?:[0-9a-f]{2}([:-]))(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}$|^[0-9a-f]{12}$")


def looks_like_mac(value: Any) -> bool:
    """Return True if *value* has the shape of a MAC address.

    For callers whose identifier argument accepts *either* a MAC or some other
    identifier, and which must know which one they were handed before deciding
    to resolve it. A substring check is not good enough: an opaque id like
    ``dev-1`` contains a separator, and a 12-hex id is indistinguishable from a
    separator-less MAC by length alone, which is why the separated form is the
    one this is used to detect in practice.
    """
    normalized = normalize_mac(value)
    return normalized is not None and _MAC_RE.match(normalized) is not None


def normalize_mac(mac: Any) -> Optional[str]:
    """Return *mac* lowercased and stripped, or ``None`` if it is not usable.

    Separators are deliberately left alone. Case is the defect this exists to
    fix; rewriting ``-`` to ``:`` would change which strings match based on a
    guess about what the caller meant, and the controller's own payloads are
    consistently colon-separated anyway.

    Anything that is not a non-empty string - ``None``, a missing dict key, an
    int - normalizes to ``None`` so it can never compare equal to a real
    address.
    """
    if not isinstance(mac, str):
        return None
    return mac.strip().lower() or None


def _mac_digits(value: Any) -> Optional[str]:
    """Return a MAC's twelve hex digits, or ``None`` if *value* is not one."""
    normalized = normalize_mac(value)
    if normalized is None or _MAC_RE.match(normalized) is None:
        return None
    return normalized.replace(":", "").replace("-", "")


def mac_equal(a: Any, b: Any) -> bool:
    """Return True if *a* and *b* are the same MAC address.

    Case and separator style are both ignored, because neither carries
    meaning: one controller surface writes a device's address
    ``1c:0b:8b:ee:f6:b5`` while another writes the same device
    ``1c0b8beef6b5``, and treating those as two devices is the same class of
    defect as treating two casings as two devices. This is not the guess
    :func:`normalize_mac` declines to make - that one is about what to SEND,
    where rewriting a separator would change the request; this is only about
    what matches.

    Values that are not MAC-shaped fall back to an exact comparison of the
    normalized strings, so opaque identifiers keep their own equality: ``dev-1``
    and ``dev1`` remain two different objects.

    Returns False whenever either side is missing or unusable. That guard is
    load-bearing: both would normalize to ``None``, and a bare ``==`` would
    then report a match between an empty query and a record carrying no
    ``mac`` field.
    """
    digits_a = _mac_digits(a)
    if digits_a is not None:
        return digits_a == _mac_digits(b)
    # Non-MAC values are opaque identifiers. Preserve their exact comparison
    # semantics: case-folding one here can select a different controller
    # resource whose identifier differs only by case.
    return isinstance(a, str) and isinstance(b, str) and bool(a) and a == b


def canonical_mac(value: Any) -> Optional[str]:
    """Return *value* as lowercase colon-separated pairs, or ``None`` if not a MAC.

    The form for a request path such as ``/stat/user/<mac>``: our convention
    (the controller accepts dashed and bare-hex forms too), and the rewrite
    :func:`normalize_mac` deliberately declines to make.
    """
    digits = _mac_digits(value)
    if digits is None:
        return None
    return ":".join(digits[i : i + 2] for i in range(0, 12, 2))


# A MAC token inside free text: six pairs with one separator style, or twelve
# bare hex digits, not adjoining another hex digit. Separators are allowed on
# either side because aiounifi writes "...stat/user/<mac>: Cannot connect".
_MAC_TOKEN_RE = re.compile(
    r"(?<![0-9a-f])(?:[0-9a-f]{2}([:-])(?:[0-9a-f]{2}\1){4}[0-9a-f]{2}|[0-9a-f]{12})(?![0-9a-f])",
    re.IGNORECASE,
)


def mask_macs(text: str) -> str:
    """Return *text* with every MAC-shaped token replaced by ``[redacted]``.

    For log lines that quote a request path, a URL or an exception message:
    ``/stat/user/<mac>`` and ``/stat/device/<mac>`` put the address in the path
    itself and aiounifi repeats the URL in its error text, and the privacy rule
    for the client and device paths is that an address never reaches a log.
    """
    return _MAC_TOKEN_RE.sub("[redacted]", text)


def normalize_mac_list(values: Any) -> Any:
    """Lowercase every MAC in a list, leaving unusable entries as they are.

    For the config payloads that carry a MAC list - ACL sides, AP-group members,
    content-filter clients, client-group members. The partial-update builders
    take the caller's raw dict and never construct their model, so a pydantic
    field validator does not run for them; this is what those builders call.

    Anything that is not a list is returned unchanged, so a caller passing a
    malformed value gets the same validation error it always did rather than a
    new one from here.
    """
    if not isinstance(values, list):
        return values
    return [normalize_mac(v) or v for v in values]
