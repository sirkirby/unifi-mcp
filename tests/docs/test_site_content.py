from __future__ import annotations

import json
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

PUBLIC_PAGES = {
    Path("docs/index.html"): "https://unifimcp.com/",
    Path("docs/sponsor/index.html"): "https://unifimcp.com/sponsor/",
    Path("docs/privacy.html"): "https://unifimcp.com/privacy.html",
}

PRODUCT_LINKS = {
    "unifi-api-server": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/api",
    "unifi-mcp-relay": "https://github.com/sirkirby/unifi-mcp/tree/main/packages/unifi-mcp-relay",
    "unifi-mcp-worker": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/worker",
}

MCP_SERVER_LINKS = {
    "unifi-network-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/network",
    "unifi-protect-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/protect",
    "unifi-access-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/access",
}

JSON_LD_PRODUCT_LINKS = MCP_SERVER_LINKS | PRODUCT_LINKS

MANIFESTS = {
    "network": Path("apps/network/src/unifi_network_mcp/tools_manifest.json"),
    "protect": Path("apps/protect/src/unifi_protect_mcp/tools_manifest.json"),
    "access": Path("apps/access/src/unifi_access_mcp/tools_manifest.json"),
}

COUNT_SURFACES = {
    "network": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/network/README.md"),
        Path("apps/network/docs/tools.md"),
        Path("plugins/unifi-network/skills/unifi-network/SKILL.md"),
    ],
    "protect": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/protect/README.md"),
        Path("apps/protect/docs/tools.md"),
        Path("plugins/unifi-protect/skills/unifi-protect/SKILL.md"),
    ],
    "access": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/access/README.md"),
        Path("apps/access/docs/tools.md"),
        Path("plugins/unifi-access/skills/unifi-access/SKILL.md"),
    ],
}

DISCOVERY_FILES = (
    Path("docs/robots.txt"),
    Path("docs/sitemap.xml"),
    Path("docs/llms.txt"),
    Path("docs/404.html"),
    Path("docs/data/project-stats.json"),
)

FORBIDDEN_PUBLIC_CLAIMS = (
    "Read-only by default",
    "full access",
    "Every tool call is logged",
    "CLI for replaying calls",
)


class SiteHTMLParser(HTMLParser):
    """Collect the small HTML surface needed by the documentation contracts."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.start_tags: list[tuple[str, dict[str, str]]] = []
        self.title_parts: list[str] = []
        self.headings: list[dict[str, str]] = []
        self.ids: list[str] = []
        self.links: list[str] = []
        self.tabs: list[dict[str, str]] = []
        self.tabpanels: list[dict[str, str]] = []
        self.json_ld: list[Any] = []
        self._title_depth = 0
        self._heading: dict[str, str] | None = None
        self._json_ld_depth = 0
        self._json_ld_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key: value or "" for key, value in attrs}
        self.start_tags.append((tag, attributes))

        element_id = attributes.get("id")
        if element_id is not None:
            self.ids.append(element_id)
        if tag == "a" and "href" in attributes:
            self.links.append(attributes["href"])
        if attributes.get("role") == "tab":
            self.tabs.append(attributes)
        if attributes.get("role") == "tabpanel":
            self.tabpanels.append(attributes)
        if tag == "title":
            self._title_depth += 1
        if tag in {"h1", "h2", "h3", "h4", "h5", "h6"}:
            self._heading = {
                "tag": tag,
                "id": attributes.get("id", ""),
                "text": "",
            }
        if tag == "script" and attributes.get("type") == "application/ld+json":
            self._json_ld_depth += 1
            self._json_ld_parts = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._title_depth:
            self._title_depth -= 1
        if self._heading is not None and tag == self._heading["tag"]:
            self._heading["text"] = " ".join(self._heading["text"].split())
            self.headings.append(self._heading)
            self._heading = None
        if tag == "script" and self._json_ld_depth:
            self._json_ld_depth -= 1
            payload = "".join(self._json_ld_parts).strip()
            if payload:
                self.json_ld.append(json.loads(payload))
            self._json_ld_parts = []

    def handle_data(self, data: str) -> None:
        if self._title_depth:
            self.title_parts.append(data)
        if self._heading is not None:
            self._heading["text"] += data
        if self._json_ld_depth:
            self._json_ld_parts.append(data)

    @property
    def title(self) -> str:
        return " ".join("".join(self.title_parts).split())

    def attributes_for(self, tag: str) -> list[dict[str, str]]:
        return [attributes for item, attributes in self.start_tags if item == tag]


def inspect_html(path: Path) -> SiteHTMLParser:
    parser = SiteHTMLParser()
    parser.feed(path.read_text(encoding="utf-8"))
    parser.close()
    return parser


def meta_content(parser: SiteHTMLParser, attribute: str, value: str) -> list[str]:
    return [
        attributes.get("content", "").strip()
        for attributes in parser.attributes_for("meta")
        if attributes.get(attribute) == value
    ]


def manifest_counts() -> dict[str, int]:
    counts: dict[str, int] = {}
    for product, path in MANIFESTS.items():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        tools = manifest["tools"]
        if manifest["count"] != len(tools):
            raise AssertionError(f"Manifest count mismatch in {path}")
        counts[product] = len(tools)
    return counts


def json_ld_nodes(value: Any) -> list[dict[str, Any]]:
    nodes: list[dict[str, Any]] = []
    if isinstance(value, dict):
        nodes.append(value)
        for child in value.values():
            nodes.extend(json_ld_nodes(child))
    elif isinstance(value, list):
        for child in value:
            nodes.extend(json_ld_nodes(child))
    return nodes


def has_json_ld_type(node: dict[str, Any], expected: str) -> bool:
    node_type = node.get("@type")
    if isinstance(node_type, list):
        return expected in node_type
    return node_type == expected


class PublicPageMetadataTests(unittest.TestCase):
    def test_pages_have_one_h1_and_unique_non_empty_titles_and_descriptions(self):
        titles: dict[str, Path] = {}
        descriptions: dict[str, Path] = {}

        for path in PUBLIC_PAGES:
            with self.subTest(path=path):
                parser = inspect_html(path)
                h1s = [heading for heading in parser.headings if heading["tag"] == "h1"]
                description = meta_content(parser, "name", "description")
                self.assertEqual(len(h1s), 1, f"{path} must contain exactly one h1")
                self.assertTrue(parser.title, f"{path} must have a non-empty title")
                self.assertEqual(len(description), 1, f"{path} must have exactly one description")
                self.assertTrue(description[0], f"{path} description must not be empty")
                self.assertNotIn(
                    parser.title,
                    titles,
                    f"Title duplicated with {titles.get(parser.title)}",
                )
                self.assertNotIn(
                    description[0],
                    descriptions,
                    f"Description duplicated with {descriptions.get(description[0])}",
                )
                titles[parser.title] = path
                descriptions[description[0]] = path

    def test_pages_have_matching_absolute_canonical_and_social_metadata(self):
        for path, expected_url in PUBLIC_PAGES.items():
            with self.subTest(path=path):
                parser = inspect_html(path)
                canonicals = [
                    attributes.get("href", "")
                    for attributes in parser.attributes_for("link")
                    if "canonical" in attributes.get("rel", "").split()
                ]
                self.assertEqual(canonicals, [expected_url])
                self.assertEqual(meta_content(parser, "property", "og:url"), [expected_url])
                og_images = meta_content(parser, "property", "og:image")
                self.assertEqual(len(og_images), 1)
                self.assertRegex(og_images[0], r"^https://")
                self.assertEqual(
                    meta_content(parser, "name", "twitter:card"),
                    ["summary_large_image"],
                )

    def test_homepage_json_ld_describes_site_source_and_products(self):
        parser = inspect_html(Path("docs/index.html"))
        nodes = [node for payload in parser.json_ld for node in json_ld_nodes(payload)]
        self.assertTrue(any(has_json_ld_type(node, "WebSite") for node in nodes))

        source_nodes = [node for node in nodes if has_json_ld_type(node, "SoftwareSourceCode")]
        self.assertEqual(
            len(source_nodes),
            1,
            "Homepage must contain exactly one SoftwareSourceCode JSON-LD node",
        )
        has_part = source_nodes[0].get("hasPart")
        self.assertIsInstance(has_part, list)
        self.assertEqual(len(has_part), len(JSON_LD_PRODUCT_LINKS))
        self.assertTrue(all(isinstance(part, dict) for part in has_part))
        product_links = {part.get("name"): part.get("url") for part in has_part}
        self.assertEqual(product_links, JSON_LD_PRODUCT_LINKS)


class CapabilityAndDiscoveryTests(unittest.TestCase):
    def test_homepage_product_tool_counts_match_manifests(self):
        parser = inspect_html(Path("docs/index.html"))
        product_elements = {
            attributes.get("data-product"): attributes.get("data-tool-count")
            for _, attributes in parser.start_tags
            if "data-product" in attributes
        }
        for product, count in manifest_counts().items():
            with self.subTest(product=product):
                self.assertIn(product, product_elements)
                self.assertEqual(product_elements[product], str(count))

    def test_discovery_files_exist(self):
        for path in DISCOVERY_FILES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"Missing discovery file: {path}")

    def test_sitemap_contains_exact_public_canonical_urls(self):
        sitemap = Path("docs/sitemap.xml")
        self.assertTrue(sitemap.is_file(), f"Missing discovery file: {sitemap}")
        root = ET.parse(sitemap).getroot()
        urls = [
            element.text.strip()
            for element in root.findall(".//{http://www.sitemaps.org/schemas/sitemap/0.9}loc")
            if element.text
        ]
        self.assertEqual(len(urls), len(PUBLIC_PAGES))
        self.assertEqual(set(urls), set(PUBLIC_PAGES.values()))

    def test_llms_txt_has_summary_and_expected_sections(self):
        path = Path("docs/llms.txt")
        self.assertTrue(path.is_file(), f"Missing discovery file: {path}")
        lines = path.read_text(encoding="utf-8").splitlines()
        self.assertGreaterEqual(len(lines), 3)
        self.assertEqual(lines[0], "# UniFi MCP")
        self.assertTrue(lines[1].startswith("> "), "Summary must immediately follow H1")
        sections = {line[3:].strip() for line in lines if line.startswith("## ")}
        for section in (
            "MCP Servers",
            "API Server",
            "Cloud Relay",
            "Safety",
            "Architecture",
            "Optional Resources",
        ):
            with self.subTest(section=section):
                self.assertIn(section, sections)


class ContentReconciliationTests(unittest.TestCase):
    def test_homepage_api_quickstart_link_uses_real_heading_fragment(self):
        homepage = Path("docs/index.html").read_text(encoding="utf-8")
        correct_url = "https://github.com/sirkirby/unifi-mcp/tree/main/apps/api#quickstart"
        incorrect_url = "https://github.com/sirkirby/unifi-mcp/tree/main/apps/api#quick-start"

        self.assertIn(correct_url, homepage)
        self.assertNotIn(incorrect_url, homepage)

    def test_user_facing_count_surfaces_match_manifests(self):
        counts = manifest_counts()
        for product, paths in COUNT_SURFACES.items():
            for path in paths:
                with self.subTest(product=product, path=path):
                    content = path.read_text(encoding="utf-8")
                    self.assertRegex(
                        content,
                        rf"(?<!\d){counts[product]}(?!\d)",
                        f"{path} must state the current {product} tool count",
                    )

    def test_readme_and_homepage_link_all_non_server_products(self):
        surfaces = {
            Path("README.md"): Path("README.md").read_text(encoding="utf-8"),
            Path("docs/index.html"): Path("docs/index.html").read_text(encoding="utf-8"),
        }
        for path, content in surfaces.items():
            for product, url in PRODUCT_LINKS.items():
                with self.subTest(path=path, product=product):
                    self.assertIn(url, content)

    def test_readme_describes_api_as_independent_non_mcp_service(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        self.assertRegex(readme, r"(?i)API[^\n]*(?:non-MCP|non MCP)")
        self.assertRegex(readme, r"(?i)independent(?:ly)?[^\n]*MCP servers")

    def test_worker_readme_uses_current_relay_contract(self):
        readme = Path("apps/worker/README.md").read_text(encoding="utf-8")
        self.assertIn("UNIFI_RELAY_TOKEN", readme)
        self.assertNotIn("UNIFI_MCP_RELAY_TOKEN", readme)
        self.assertRegex(readme, r"(?i)relay[^\n]*(?:MCP over HTTP|MCP HTTP)")
        self.assertNotRegex(readme, r"(?i)relay[^\n]*stdio")

    def test_public_pages_do_not_make_outdated_claims(self):
        for path in PUBLIC_PAGES:
            content = path.read_text(encoding="utf-8")
            for claim in FORBIDDEN_PUBLIC_CLAIMS:
                with self.subTest(path=path, claim=claim):
                    self.assertNotIn(claim, content)


if __name__ == "__main__":
    unittest.main()
