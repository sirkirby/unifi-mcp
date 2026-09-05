"""Contracts for generated marketplace support-bundle skills."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PRODUCTS = {
    "network": "unifi_get_support_bundle",
    "protect": "protect_get_support_bundle",
    "access": "access_get_support_bundle",
}
GUIDE_URL = "https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md"


def skill_path(product: str) -> Path:
    return ROOT / "plugins" / f"unifi-{product}" / "skills" / f"unifi-{product}-support" / "SKILL.md"


def test_generated_support_skills_have_no_drift() -> None:
    result = subprocess.run(
        [sys.executable, "scripts/generate_support_skills.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_product_plugins_package_the_generated_support_skills() -> None:
    for product, tool in PRODUCTS.items():
        plugin = json.loads((ROOT / "plugins" / f"unifi-{product}" / ".codex-plugin" / "plugin.json").read_text())
        declared_root = (ROOT / "plugins" / f"unifi-{product}" / plugin["skills"]).resolve()
        path = skill_path(product)
        assert path.is_relative_to(declared_root)
        assert path.exists()
        assert f"name: unifi-{product}-support" in path.read_text()
        assert tool in path.read_text()


def test_support_skills_preserve_the_review_before_share_boundary() -> None:
    forbidden = (
        "disable redaction",
        "post the bundle automatically",
        "upload the bundle automatically",
        "ask the user for credentials",
        "collect the raw logs",
    )
    for product in PRODUCTS:
        text = skill_path(product).read_text()
        normalized = " ".join(text.split())
        assert GUIDE_URL in text
        assert "sanitized, not anonymous" in text
        assert "Show the complete returned JSON" in text
        assert "pause before any external sharing" in normalized
        assert "If the server cannot start or register tools" in normalized
        assert "Do not ask for credentials" in normalized
        assert "must never upload, attach, paste, post, or submit the bundle" in normalized
        assert "unless the user makes a separate explicit request" not in normalized
        assert "any publication must happen outside this support workflow" in normalized
        for phrase in forbidden:
            assert phrase not in text.lower()


def test_protect_skill_explains_unsupported_shape_with_real_tool_and_summary_fallback() -> None:
    text = skill_path("protect").read_text()
    assert 'protect_get_support_bundle(probe="resource_shape", resource="sensors")' in text
    assert '`resource_shape(resource="sensors")`' not in text
    assert "currently returns `unsupported`" in text
    assert "use `summary`" in text
    assert "Do not request or call this probe in the current release" in text
    assert "resource_shape" not in skill_path("network").read_text()
    assert "resource_shape" not in skill_path("access").read_text()
