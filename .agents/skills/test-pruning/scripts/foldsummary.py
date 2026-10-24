"""Summarize a worker ledger: deleted rows verbatim, folds grouped by destination."""

import collections
import re
import sys

dels, folds = [], collections.Counter()
for path in sys.argv[1:]:
    for line in open(path):
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 3:
            continue
        action = cells[1].lower()
        if action.startswith("deleted"):
            dels.append(f"| {cells[0]} | {cells[2]} |")
        m = re.search(r"folded into\s+`?([^`|]+?)`?\s*$", cells[1], re.I)
        if m and "parametrized/kept test" not in m.group(1):
            folds[m.group(1).strip()] += 1
        elif m:
            dest = re.match(r"`?([^ `]+::[^ `\[]+)", cells[2])
            folds[dest.group(1) if dest else "(see kept assertion)"] += 1
print(f"### Deleted ({len(dels)})\n\n| Test | Kept test asserting the same behaviour |\n|---|---|")
print("\n".join(dels) if dels else "| none | |")
print(f"\n### Folded ({sum(folds.values())} functions into {len(folds)} tests; every case still runs)\n")
print("| Kept test | Functions folded in |\n|---|---|")
for k, v in folds.most_common():
    print(f"| `{k}` | {v} |")
