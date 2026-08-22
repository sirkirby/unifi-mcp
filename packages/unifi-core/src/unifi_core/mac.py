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

__all__ = ["normalize_mac", "mac_equal", "looks_like_mac", "normalize_mac_list"]

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


def mac_equal(a: Any, b: Any) -> bool:
    """Return True if *a* and *b* are the same MAC address, ignoring case.

    Returns False whenever either side is missing or unusable. That guard is
    load-bearing: both would normalize to ``None``, and a bare ``==`` would
    then report a match between an empty query and a record carrying no
    ``mac`` field.
    """
    normalized = normalize_mac(a)
    return normalized is not None and normalized == normalize_mac(b)


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
