"""Fail when a suite stops covering a branch arc it is responsible for.

usage: python3 arcdiff.py <suite> <baseline-dir> <after-coverage-file>

An arc in the suite's own package must stay covered. An arc in another package
may be dropped only when that package's own suite covers it (its baseline in
<baseline-dir>/base.<owner>.coverage), which is how CI measures coverage.
Exit status 1 and a LOST line per arc when anything required was lost.
"""

import re
import sqlite3
import sys

suite, base_dir, after_file = sys.argv[1:4]
MODULE_OWNER = {
    "unifi_core": "core",
    "unifi_mcp_shared": "shared",
    "unifi_mcp_relay": "relay",
    "unifi_network_mcp": "network",
    "unifi_protect_mcp": "protect",
    "unifi_access_mcp": "access",
    "unifi_api": "api",
}


def arcs(path):
    db = sqlite3.connect(path)
    files = {}
    for i, p in db.execute("select id, path from file"):
        m = re.search(r"/src/((unifi_[a-z_]+)/.*)$", p)
        files[i] = (m.group(1), m.group(2)) if m else (None, None)
    return {(files[f], a, b) for f, a, b in db.execute("select file_id, fromno, tono from arc") if files[f][0]}


before = arcs(f"{base_dir}/base.{suite}.coverage")
after = arcs(after_file)
owner_cover = {}
lost = []
for (rel, module), a, b in sorted(before - after):
    owner = MODULE_OWNER.get(module)
    if owner and owner != suite:
        if owner not in owner_cover:
            owner_cover[owner] = {(r, x, y) for (r, _), x, y in arcs(f"{base_dir}/base.{owner}.coverage")}
        if (rel, a, b) in owner_cover[owner]:
            continue
    lost.append((rel, a, b))
print(f"suite {suite}: before {len(before)} arcs, after {len(after)}, required arcs lost {len(lost)}")
for x in lost[:60]:
    print("LOST", *x)
sys.exit(1 if lost else 0)
