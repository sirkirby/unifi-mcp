#!/usr/bin/env python3
"""Generate tool reference tables for the UniFi skill from tool manifests.

Reads each server's tools_manifest.json and updates the skill reference
docs with accurate tool tables. Hand-written sections (tips, scenarios)
are preserved — only content between AUTO markers is replaced.

Usage:
    python scripts/generate_skill_references.py [--check]

Flags:
    --check   Dry-run mode: report drift without modifying files (exit 1 if drift found)

Markers in reference files:
    <!-- AUTO:tools:CATEGORY_NAME -->
    ...auto-generated tool table...
    <!-- /AUTO:tools:CATEGORY_NAME -->
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
PLUGINS_DIR = REPO_ROOT / "plugins"

# Server configs — reference files live in each plugin's skill directory
SERVERS = [
    {
        "name": "network",
        "manifest": REPO_ROOT / "apps" / "network" / "src" / "unifi_network_mcp" / "tools_manifest.json",
        "reference": PLUGINS_DIR / "unifi-network" / "skills" / "unifi-network" / "references" / "network-tools.md",
        "module_strip": "unifi_network_mcp.tools.",
    },
    {
        "name": "protect",
        "manifest": REPO_ROOT / "apps" / "protect" / "src" / "unifi_protect_mcp" / "tools_manifest.json",
        "reference": PLUGINS_DIR / "unifi-protect" / "skills" / "unifi-protect" / "references" / "protect-tools.md",
        "module_strip": "unifi_protect_mcp.tools.",
    },
    {
        "name": "access",
        "manifest": REPO_ROOT / "apps" / "access" / "src" / "unifi_access_mcp" / "tools_manifest.json",
        "reference": PLUGINS_DIR / "unifi-access" / "skills" / "unifi-access" / "references" / "access-tools.md",
        "module_strip": "unifi_access_mcp.tools.",
    },
]


def load_manifest(path: Path) -> dict:
    """Load a tools_manifest.json file."""
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def first_sentence(text: str) -> str:
    """Extract the first sentence from a description.

    Keeps it readable in a table cell. If the first sentence is over
    140 chars, truncate with ellipsis.
    """
    # Split on period followed by space or end-of-string
    match = re.match(r"^(.+?\.)\s", text)
    sentence = match.group(1) if match else text
    if len(sentence) > 140:
        sentence = sentence[:137] + "..."
    return sentence


def classify_tool(tool: dict) -> str:
    """Classify a tool as Read or Mutate based on confirm parameter."""
    props = tool.get("schema", {}).get("input", {}).get("properties", {})
    return "Mutate" if "confirm" in props else "Read"


def group_by_category(manifest: dict, module_strip: str) -> dict[str, list[dict]]:
    """Group tools by category (module name) from the manifest."""
    module_map = manifest.get("module_map", {})
    tools_by_name = {t["name"]: t for t in manifest.get("tools", [])}

    categories: dict[str, list[dict]] = {}
    for tool_name, module_path in sorted(module_map.items()):
        category = module_path.replace(module_strip, "")
        if category not in categories:
            categories[category] = []

        tool = tools_by_name.get(tool_name)
        if tool:
            categories[category].append(
                {
                    "name": tool["name"],
                    "type": classify_tool(tool),
                    "description": first_sentence(tool["description"]),
                }
            )

    # Sort: reads first, then mutates, alphabetical within each group
    for cat in categories:
        categories[cat].sort(key=lambda t: (0 if t["type"] == "Read" else 1, t["name"]))

    return categories


def generate_table(tools: list[dict]) -> str:
    """Generate a markdown table for a list of tools."""
    lines = [
        f"{len(tools)} tools.",
        "",
        "| Tool | Type | Description |",
        "|------|------|-------------|",
    ]
    for t in tools:
        lines.append(f"| `{t['name']}` | {t['type']} | {t['description']} |")

    return "\n".join(lines)


def find_markers(content: str) -> list[tuple[str, list[str]]]:
    """Find all AUTO:tools markers and their associated categories.

    Supports comma-separated categories: <!-- AUTO:tools:system,config -->
    Returns list of (marker_key, [category_names]).
    """
    pattern = re.compile(r"<!-- AUTO:tools:([\w,]+) -->")
    markers = []
    for match in pattern.finditer(content):
        marker_key = match.group(1)
        cats = [c.strip() for c in marker_key.split(",")]
        markers.append((marker_key, cats))
    return markers


def update_reference_content(content: str, categories: dict[str, list[dict]]) -> tuple[str, int, int, list[str]]:
    """Update auto-generated sections in reference file content.

    Supports comma-separated categories in markers for merging:
    <!-- AUTO:tools:system,config --> merges tools from both modules.

    Returns (new_content, updated_count, missing_count, missing_categories).
    """
    markers = find_markers(content)
    matched_cats: set[str] = set()
    updated = 0

    for marker_key, cat_list in markers:
        start_marker = f"<!-- AUTO:tools:{marker_key} -->"
        end_marker = f"<!-- /AUTO:tools:{marker_key} -->"

        pattern = re.compile(
            re.escape(start_marker) + r".*?" + re.escape(end_marker),
            re.DOTALL,
        )

        # Merge tools from all categories in this marker
        merged_tools = []
        for cat in cat_list:
            if cat in categories:
                merged_tools.extend(categories[cat])
                matched_cats.add(cat)

        if not merged_tools:
            continue

        # Sort merged: reads first, then mutates, alphabetical within
        merged_tools.sort(key=lambda t: (0 if t["type"] == "Read" else 1, t["name"]))

        table = generate_table(merged_tools)
        replacement = f"{start_marker}\n{table}\n{end_marker}"

        new_content, count = pattern.subn(replacement, content)
        if count > 0:
            content = new_content
            updated += 1

    # Find categories without markers
    missing_cats = [c for c in categories if c not in matched_cats]

    return content, updated, len(missing_cats), missing_cats


def update_header_count(content: str, total_tools: int, server_name: str) -> str:
    """Update the tool count in the file's H1 header."""
    # Match patterns like "# Network Server Tool Reference (91 tools)"
    pattern = re.compile(r"(# \w+ Server Tool Reference )\(\d+ tools\)")
    return pattern.sub(rf"\g<1>({total_tools} tools)", content)


def main():
    check_mode = "--check" in sys.argv
    mode_label = "Checking" if check_mode else "Generating"

    print(f"{mode_label} skill reference tables from tool manifests...")

    total_updated = 0
    total_missing = 0
    all_missing_cats: list[tuple[str, str]] = []
    has_drift = False

    for server in SERVERS:
        manifest_path = server["manifest"]
        reference_path = server["reference"]

        if not manifest_path.exists():
            print(f"  SKIP: Manifest not found for {server['name']}: {manifest_path}")
            continue

        if not reference_path.exists():
            print(f"  SKIP: Reference not found for {server['name']}: {reference_path}")
            continue

        print(f"\n  {server['name'].title()} Server:")
        manifest = load_manifest(manifest_path)
        categories = group_by_category(manifest, server["module_strip"])

        print(f"    Manifest: {manifest['count']} tools in {len(categories)} categories")

        content = reference_path.read_text(encoding="utf-8")
        new_content, updated, missing, missing_cats = update_reference_content(content, categories)
        new_content = update_header_count(new_content, manifest["count"], server["name"])

        if new_content != content:
            has_drift = True
            if not check_mode:
                reference_path.write_text(new_content, encoding="utf-8")

        total_updated += updated
        total_missing += missing

        for cat in missing_cats:
            all_missing_cats.append((server["name"], cat))

        print(f"    Updated: {updated} categories, Missing markers: {missing}")

    if check_mode:
        # total_updated counts the sections rendered, not the ones that differ:
        # has_drift is the real signal. Saying "would update" when nothing would
        # change reads as drift on a clean checkout.
        print(f"\nDone. Checked {total_updated} sections; {'drift found' if has_drift else 'no drift'}.")
    else:
        print(f"\nDone. Updated {total_updated} sections.")

    if total_missing > 0:
        print(f"\n{total_missing} categories missing markers:")
        for server_name, cat in all_missing_cats:
            print(f"  {server_name}: <!-- AUTO:tools:{cat} --> ... <!-- /AUTO:tools:{cat} -->")

    if check_mode and has_drift:
        print("\nDrift detected! Run without --check to update.")
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
