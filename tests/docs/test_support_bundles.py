from __future__ import annotations

import unittest
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
GUIDE_PATH = Path("docs/support-bundles.md")
GUIDE_URL = "https://github.com/sirkirby/unifi-mcp/blob/main/docs/support-bundles.md"
TOOLS = (
    "unifi_get_support_bundle",
    "protect_get_support_bundle",
    "access_get_support_bundle",
)


class SupportBundleDocumentationTests(unittest.TestCase):
    def test_canonical_guide_covers_workflow_and_privacy_contract(self) -> None:
        guide = (ROOT / GUIDE_PATH).read_text()
        for tool in TOOLS:
            self.assertIn(tool, guide)
        for phrase in (
            "summary",
            "connectivity",
            "resource_shape",
            "Dragging a file into GitHub begins publication/upload",
            "sanitized, not anonymous",
            "UNIFI_MCP_DIAGNOSTICS",
            "cannot diagnose a failure that prevents the server from starting",
            "performs no secondary upload",
            "unavailable through every cloud relay path",
            "32 KiB",
        ):
            self.assertIn(phrase, guide)

    def test_all_support_entrypoints_link_to_the_canonical_guide(self) -> None:
        relative_surfaces = (
            "README.md",
            "SUPPORT.md",
            "CONTRIBUTING.md",
            "docs/README.md",
            "apps/network/docs/troubleshooting.md",
            "apps/protect/docs/troubleshooting.md",
            "apps/access/docs/troubleshooting.md",
        )
        for relative in relative_surfaces:
            text = (ROOT / relative).read_text()
            self.assertIn("support-bundles.md", text, relative)

        form = (ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml").read_text()
        config = (ROOT / ".github/ISSUE_TEMPLATE/config.yml").read_text()
        self.assertIn(GUIDE_URL, form)
        self.assertIn(GUIDE_URL, config)

    def test_bug_form_support_bundle_is_optional_unrendered_and_before_raw_evidence(self) -> None:
        form_path = ROOT / ".github/ISSUE_TEMPLATE/bug_report.yml"
        raw = form_path.read_text()
        form = yaml.safe_load(raw)
        body = form["body"]
        support_index = next(index for index, item in enumerate(body) if item.get("id") == "support_bundle")
        raw_index = next(index for index, item in enumerate(body) if item.get("id") == "raw_tool_output")
        logs_index = next(index for index, item in enumerate(body) if item.get("id") == "logs")
        support = body[support_index]

        self.assertEqual(support["type"], "textarea")
        self.assertNotIn("render", support["attributes"])
        self.assertNotIn("validations", support)
        self.assertLess(support_index, raw_index)
        self.assertLess(support_index, logs_index)
        self.assertEqual(raw.count("id: support_bundle"), 1)
        self.assertIn(GUIDE_URL, support["attributes"]["description"])
        for tool in TOOLS:
            self.assertIn(tool, support["attributes"]["description"])


if __name__ == "__main__":
    unittest.main()
