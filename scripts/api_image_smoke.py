#!/usr/bin/env python3
"""Image-level smoke harness for unifi-api-server.

Hits every GET endpoint exposed by the running container and asserts
none of them return 5xx. Distinct from `scripts/live_api_smoke.py`,
which runs the API in-process via ASGITransport and therefore can't
detect dep-closure bugs that only manifest in the published image.

Usage:
    # Container must already be running (e.g. via scripts/start-api.sh).
    # Pass the bootstrap admin key as $1 (or via UNIFI_API_KEY env).
    # Optionally pass the registered controller UUID as $2.
    python scripts/api_image_smoke.py <admin-key> [<controller-id>]

Exit code:
    0  no 5xx responses
    1  one or more 5xx responses (details printed)
    2  schema fetch failed / container unreachable

Buckets reported:
    200 ok                              — endpoint working
    409 capability-mismatch             — expected when only some products are registered
    404/422 not-found / validation      — expected for unknown-ID sentinels
    501 not-implemented (api_key_required) — DPI without a token (expected when unset)
    5xx server-error                    — REAL BUGS, fail
    network/timeout                     — container unreachable, fail
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("UNIFI_API_BASE", "http://localhost:8089")
SITE = os.environ.get("UNIFI_API_SITE", "default")
SENTINEL = "__none__"


def _hit(url: str, key: str) -> tuple[int, str, float]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {key}", "Accept": "application/json"},
    )
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read(8192).decode("utf-8", errors="replace")
            return resp.status, body, (time.perf_counter() - start) * 1000
    except urllib.error.HTTPError as e:
        body = e.read(8192).decode("utf-8", errors="replace")
        return e.code, body, (time.perf_counter() - start) * 1000
    except Exception as e:
        return 0, f"{type(e).__name__}: {e}", (time.perf_counter() - start) * 1000


def _resolve_path(path: str, params: dict[str, str]) -> str:
    out = path
    for key, value in params.items():
        out = out.replace("{" + key + "}", urllib.parse.quote(value, safe=""))
    while "{" in out and "}" in out:
        left = out.index("{")
        right = out.index("}", left)
        out = out[:left] + SENTINEL + out[right + 1 :]
    return out


def _classify(status: int, body: str) -> str:
    if status == 0:
        return "network/timeout"
    if status == 501:
        # The api_key_required path is an expected, well-formed response;
        # bucket separately so it doesn't get conflated with real 5xx.
        try:
            detail = json.loads(body).get("detail") or {}
            if isinstance(detail, dict) and detail.get("kind") == "api_key_required":
                return "501 api-key-required (expected without controller API token)"
        except Exception:
            pass
        return f"{status} server-error"
    if status >= 500:
        return f"{status} server-error"
    if status == 409:
        try:
            detail = json.loads(body).get("detail") or {}
            if isinstance(detail, dict) and detail.get("kind") == "capability_mismatch":
                return "409 capability-mismatch (expected for unregistered products)"
        except Exception:
            pass
        return f"{status} client-error"
    if status == 404:
        return "404 not-found (expected for unknown-ID sentinels)"
    if status == 422:
        return "422 validation (expected for sentinel input)"
    if status >= 400:
        return f"{status} client-error"
    return f"{status} ok"


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__, file=sys.stderr)
        return 2
    key = argv[1]
    controller_id = argv[2] if len(argv) > 2 else None

    params: dict[str, str] = {"site_id": SITE}
    if controller_id:
        params["cid"] = controller_id
        params["controller"] = controller_id

    try:
        with urllib.request.urlopen(f"{BASE}/v1/openapi.json", timeout=10) as r:
            schema = json.load(r)
    except Exception as e:
        print(f"FAIL: could not fetch OpenAPI schema from {BASE}: {e}", file=sys.stderr)
        return 2

    rows: list[dict] = []
    for path, ops in schema["paths"].items():
        if "get" not in ops:
            continue
        if path.startswith("/v1/streams/"):
            continue  # SSE streams won't terminate cleanly via urlopen
        url = BASE + _resolve_path(path, params)
        status, body, ms = _hit(url, key)
        rows.append({"path": path, "url": url, "status": status, "ms": ms, "body": body})

    buckets: dict[str, list[dict]] = {}
    for r in rows:
        buckets.setdefault(_classify(r["status"], r["body"]), []).append(r)

    print(f"Swept {len(rows)} GET endpoints against {BASE}")
    print()
    for key in sorted(buckets, key=lambda k: ("ok" not in k, "expected" not in k, k)):
        print(f"  [{len(buckets[key]):3d}]  {key}")
    print()

    failures = [
        r for k, rows in buckets.items() for r in rows if (k.startswith(("5", "network")) and "expected" not in k)
    ]
    if not failures:
        print("PASS — no 5xx / network failures.")
        return 0

    print("=" * 70)
    print(f"FAIL — {len(failures)} endpoint(s) returned 5xx or network failure")
    print("=" * 70)
    for r in failures:
        print(f"  {r['status']}  {r['path']}  ({int(r['ms'])}ms)")
        print(f"    {r['body'][:300]}")
    return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
