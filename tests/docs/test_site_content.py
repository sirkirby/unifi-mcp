from __future__ import annotations

import importlib.util
import json
import re
import sys
import unittest
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urljoin, urlparse

PUBLIC_PAGES = {
    Path("docs/index.html"): "https://unifimcp.com/",
    Path("docs/sponsor/index.html"): "https://unifimcp.com/sponsor/",
    Path("docs/privacy.html"): "https://unifimcp.com/privacy.html",
}

LINKED_HTML_PAGES = PUBLIC_PAGES | {
    Path("docs/404.html"): "https://unifimcp.com/404.html",
}

SITE_ORIGIN = "https://unifimcp.com"
REPOSITORY_URL = "https://github.com/sirkirby/unifi-mcp"

PRODUCT_LINKS = {
    "unifi-api-server": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/api",
    "unifi-mcp-relay": "https://github.com/sirkirby/unifi-mcp/tree/main/packages/unifi-mcp-relay",
    "unifi-mcp-worker": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/worker",
}

MCP_SERVER_LINKS = {
    "unifi-network-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/network",
    "unifi-protect-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/protect",
    "unifi-access-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/access",
    "unifi-sitemanager-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/sitemanager",
}

# The InnerSpace and Drive servers are on the homepage once released, but the
# download-stats snapshot and the site's package lists (app.js) do not cover them yet.
INNERSPACE_SERVER_LINKS = {
    "unifi-innerspace-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/innerspace",
}
DRIVE_SERVER_LINKS = {
    "unifi-drive-mcp": "https://github.com/sirkirby/unifi-mcp/tree/main/apps/drive",
}

JSON_LD_PRODUCT_LINKS = MCP_SERVER_LINKS | PRODUCT_LINKS

MANIFESTS = {
    "network": Path("apps/network/src/unifi_network_mcp/tools_manifest.json"),
    "protect": Path("apps/protect/src/unifi_protect_mcp/tools_manifest.json"),
    "access": Path("apps/access/src/unifi_access_mcp/tools_manifest.json"),
    "sitemanager": Path("apps/sitemanager/src/unifi_sitemanager_mcp/tools_manifest.json"),
    "innerspace": Path("apps/innerspace/src/unifi_innerspace_mcp/tools_manifest.json"),
    "drive": Path("apps/drive/src/unifi_drive_mcp/tools_manifest.json"),
}

# Whether unifi-sitemanager-mcp has a first release. Until it does, public pages
# must not present an install command, badge or marketplace link as working.
SITEMANAGER_RELEASED = True

# Install surfaces that only work once the Site Manager package is published.
SITEMANAGER_RELEASE_ONLY_TEXT = (
    "uvx unifi-sitemanager-mcp",
    "pip install unifi-sitemanager-mcp",
    "pipx install unifi-sitemanager-mcp",
    "docker pull ghcr.io/sirkirby/unifi-sitemanager-mcp",
    "unifi-sitemanager@unifi-plugins",
    "pypi.org/project/unifi-sitemanager-mcp",
    "img.shields.io/pypi/v/unifi-sitemanager-mcp",
)

# Whether unifi-innerspace-mcp has a first release. Until it does, no page may
# present an install command, badge or marketplace link for it as working.
INNERSPACE_RELEASED = True

# Install surfaces that only work once the InnerSpace package is published.
INNERSPACE_RELEASE_ONLY_TEXT = (
    "uvx unifi-innerspace-mcp",
    "pip install unifi-innerspace-mcp",
    "pipx install unifi-innerspace-mcp",
    "docker pull ghcr.io/sirkirby/unifi-innerspace-mcp",
    "unifi-innerspace@unifi-plugins",
    "pypi.org/project/unifi-innerspace-mcp",
    "img.shields.io/pypi/v/unifi-innerspace-mcp",
)

# Install surfaces that only work once the Drive package is published. It is
# released, so these must be present on the pages that install servers.
DRIVE_RELEASE_ONLY_TEXT = (
    "uvx unifi-drive-mcp",
    "pip install unifi-drive-mcp",
    "pipx install unifi-drive-mcp",
    "docker pull ghcr.io/sirkirby/unifi-drive-mcp",
    "unifi-drive@unifi-plugins",
    "pypi.org/project/unifi-drive-mcp",
    "img.shields.io/pypi/v/unifi-drive-mcp",
)

# Public pages that describe the servers. The Site Manager app's own README
# keeps its release-gated instructions under a heading that says so.
SERVER_SURFACES = (
    Path("README.md"),
    Path("QUICKSTART.md"),
    Path("CONTRIBUTING.md"),
    Path("SECURITY.md"),
    Path("SUPPORT.md"),
    Path("PRIVACY.md"),
    Path(".env.example"),
    Path("docs/index.html"),
    Path("docs/404.html"),
    Path("docs/sponsor/index.html"),
    Path("docs/privacy.html"),
    Path("docs/llms.txt"),
    Path("docs/README.md"),
    Path("docs/tool-index.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/agent-install.md"),
    Path("docs/credential-providers.md"),
    Path("docs/permissions.md"),
    Path("docs/cross-product.md"),
    Path("docs/support-bundles.md"),
    Path("docs/tls-verification.md"),
    Path("apps/network/docs/transports.md"),
    Path("apps/api/README.md"),
)

# The InnerSpace app's own pages, which are checked against the same gate.
INNERSPACE_APP_PAGES = (
    Path("apps/innerspace/README.md"),
    Path("apps/innerspace/docs/configuration.md"),
    Path("apps/innerspace/docs/permissions.md"),
    Path("apps/innerspace/docs/tools.md"),
    Path("apps/innerspace/docs/troubleshooting.md"),
)

# The Drive app's own pages.
DRIVE_APP_PAGES = (
    Path("apps/drive/README.md"),
    Path("apps/drive/docs/configuration.md"),
    Path("apps/drive/docs/permissions.md"),
    Path("apps/drive/docs/tools.md"),
    Path("apps/drive/docs/troubleshooting.md"),
)

COUNT_SURFACES = {
    "network": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/network/README.md"),
        Path("apps/network/docs/tools.md"),
    ],
    "protect": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/protect/README.md"),
        Path("apps/protect/docs/tools.md"),
    ],
    "access": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/access/README.md"),
        Path("apps/access/docs/tools.md"),
    ],
    # Site Manager states its nine domain tools; its own docs spell the number out.
    "sitemanager": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
    ],
    # InnerSpace does the same: its domain tools (reads and writes), without the meta-tools.
    "innerspace": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/innerspace/docs/tools.md"),
    ],
    # Drive counts its domain tools the same way: 22, without the meta-tools.
    "drive": [
        Path("README.md"),
        Path("docs/ARCHITECTURE.md"),
        Path("apps/drive/docs/tools.md"),
    ],
}

# Plugin skills describe the server release their plugin pins, not the
# workspace server: their counts move in the plugin release that moves the pin.
PLUGIN_COUNT_SURFACES = {
    product: [Path(f"plugins/unifi-{product}/skills/unifi-{product}/SKILL.md")]
    for product in ("network", "protect", "access")
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


def _plugin_tool_refs():
    """``scripts/plugin_tool_refs.py``, which resolves each plugin's pinned server release."""
    scripts = Path("scripts").resolve()
    if str(scripts) not in sys.path:
        sys.path.insert(0, str(scripts))
    if "plugin_tool_refs" in sys.modules:
        return sys.modules["plugin_tool_refs"]
    spec = importlib.util.spec_from_file_location("plugin_tool_refs", scripts / "plugin_tool_refs.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def states_count(content: str, count: int) -> bool:
    """Whether ``content`` states ``count`` as a whole number."""
    return re.search(rf"(?<!\d){count}(?!\d)", content) is not None


def pinned_counts(root: Path = Path(".")) -> dict[str, int]:
    """Tool counts of the server releases the product plugins pin, read from their release tags."""
    refs = _plugin_tool_refs()
    return {product: refs.pinned_tool_count(root.resolve(), product) for product in PLUGIN_COUNT_SURFACES}


def manifest_counts() -> dict[str, int]:
    """Published tool counts: every manifest tool, except Site Manager, InnerSpace and Drive (domain tools only)."""
    refs = _plugin_tool_refs()
    counts: dict[str, int] = {}
    for product, path in MANIFESTS.items():
        manifest = json.loads(path.read_text(encoding="utf-8"))
        tools = manifest["tools"]
        if manifest["count"] != len(tools):
            raise AssertionError(f"Manifest count mismatch in {path}")
        # Drive's domain tools are its module_map entries, as for Site Manager and InnerSpace.
        counts[product] = len(manifest["module_map"]) if product == "drive" else refs.tool_count(manifest, product)
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


def site_url_to_path(url: str) -> Path:
    parsed = urlparse(url)
    relative = unquote(parsed.path).lstrip("/")
    if not relative:
        return Path("docs/index.html")
    if parsed.path.endswith("/"):
        return Path("docs") / relative / "index.html"
    return Path("docs") / relative


def markdown_links(content: str) -> list[str]:
    return re.findall(r"\[[^\]]+\]\(([^)\s]+)\)", content)


def _css_selector_matches_link(selector: str, *, ancestors: set[str]) -> bool:
    selector = selector.strip()
    if not selector or ":" in selector:
        return False
    tokens = [token for token in re.split(r"\s+|\s*>\s*", selector) if token]
    if not tokens:
        return False
    target = tokens[-1]
    if target not in {"a", "*"}:
        return False
    for token in tokens[:-1]:
        if token.startswith(".") and token[1:] not in ancestors:
            return False
        if not token.startswith(".") and token not in ancestors:
            return False
    return True


def _css_specificity(selector: str) -> tuple[int, int, int]:
    ids = len(re.findall(r"#[\w-]+", selector))
    classes = len(re.findall(r"\.[\w-]+|\[[^]]+\]", selector))
    tags = len(re.findall(r"(?<![.#\w-])[a-zA-Z][\w-]*", selector))
    return ids, classes, tags


def link_has_non_color_cue(css: str, *, ancestors: set[str]) -> bool:
    winning: dict[str, tuple[tuple[int, int, int, int, int, int], str]] = {}
    order = 0
    for rule in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selectors = rule.group(1).split(",")
        declarations = rule.group(2).split(";")
        for selector in selectors:
            if not _css_selector_matches_link(selector, ancestors=ancestors):
                continue
            specificity = _css_specificity(selector)
            for declaration_order, declaration in enumerate(declarations):
                if ":" not in declaration:
                    continue
                property_name, value = (part.strip().lower() for part in declaration.split(":", 1))
                important = value.endswith("!important")
                value = value.removesuffix("!important").strip()
                if property_name in {"text-decoration", "text-decoration-line"}:
                    cue = "text-decoration"
                elif property_name in {"border-bottom", "border-bottom-style"}:
                    cue = "border-bottom"
                else:
                    continue
                priority = (int(important), *specificity, order, declaration_order)
                if cue not in winning or priority > winning[cue][0]:
                    winning[cue] = (priority, value)
        order += 1

    text_decoration = winning.get("text-decoration", ((0, 0, 0, 0, 0, 0), "none"))[1]
    border_bottom = winning.get("border-bottom", ((0, 0, 0, 0, 0, 0), "none"))[1]
    return text_decoration not in {"none", "initial", "unset"} or border_bottom not in {
        "none",
        "0",
        "0px",
        "initial",
        "unset",
    }


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
        unique_values: dict[str, dict[str, Path]] = {
            "og:title": {},
            "og:description": {},
            "twitter:title": {},
            "twitter:description": {},
        }
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
                for field in (
                    "og:title",
                    "og:description",
                    "og:image",
                    "og:image:width",
                    "og:image:height",
                    "og:image:alt",
                ):
                    values = meta_content(parser, "property", field)
                    self.assertEqual(len(values), 1, f"{path} must have exactly one {field}")
                    self.assertTrue(values[0], f"{path} {field} must not be empty")
                self.assertEqual(meta_content(parser, "property", "og:image:width"), ["1200"])
                self.assertEqual(meta_content(parser, "property", "og:image:height"), ["675"])
                self.assertRegex(meta_content(parser, "property", "og:image")[0], r"^https://")
                self.assertEqual(
                    meta_content(parser, "name", "twitter:card"),
                    ["summary_large_image"],
                )
                for field in (
                    "twitter:title",
                    "twitter:description",
                    "twitter:image",
                    "twitter:image:alt",
                ):
                    values = meta_content(parser, "name", field)
                    self.assertEqual(len(values), 1, f"{path} must have exactly one {field}")
                    self.assertTrue(values[0], f"{path} {field} must not be empty")
                self.assertEqual(
                    meta_content(parser, "name", "twitter:image"),
                    meta_content(parser, "property", "og:image"),
                )

                for field, values in unique_values.items():
                    attribute = "property" if field.startswith("og:") else "name"
                    value = meta_content(parser, attribute, field)[0]
                    self.assertNotIn(value, values, f"{field} duplicated with {values.get(value)}")
                    values[value] = path

    def test_privacy_description_distinguishes_local_first_and_optional_relay(self):
        parser = inspect_html(Path("docs/privacy.html"))
        descriptions = meta_content(parser, "name", "description")

        self.assertEqual(len(descriptions), 1)
        self.assertIn("local-first", descriptions[0])
        self.assertIn("optional Cloud Relay", descriptions[0])
        self.assertNotIn(
            "All communication stays between your AI agent and your local UniFi controller",
            descriptions[0],
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
        expected = JSON_LD_PRODUCT_LINKS | (INNERSPACE_SERVER_LINKS if INNERSPACE_RELEASED else {}) | DRIVE_SERVER_LINKS
        self.assertEqual(len(has_part), len(expected))
        self.assertTrue(all(isinstance(part, dict) for part in has_part))
        product_links = {part.get("name"): part.get("url") for part in has_part}
        self.assertEqual(product_links, expected)


class PublicPageAccessibilityContractTests(unittest.TestCase):
    def test_public_pages_have_one_main_landmark(self):
        for path in PUBLIC_PAGES:
            with self.subTest(path=path):
                parser = inspect_html(path)
                self.assertEqual(
                    len(parser.attributes_for("main")),
                    1,
                    f"{path} must contain exactly one main landmark",
                )

    def test_homepage_momentum_definition_list_uses_terms_and_definitions(self):
        html = Path("docs/index.html").read_text(encoding="utf-8")
        metrics = html.split('<dl class="metrics">', maxsplit=1)[1].split("</dl>", maxsplit=1)[0]

        self.assertNotIn("<p", metrics)
        self.assertEqual(metrics.count("<dt>"), 3)
        self.assertEqual(metrics.count("<dd"), 6)

    def test_privacy_text_links_have_a_non_color_cue_after_css_cascade(self):
        html = Path("docs/privacy.html").read_text(encoding="utf-8")
        style = re.search(r"<style>(.*?)</style>", html, flags=re.DOTALL)
        self.assertIsNotNone(style)
        css = style.group(1)

        self.assertTrue(link_has_non_color_cue(css, ancestors={"p"}))
        self.assertTrue(link_has_non_color_cue(css, ancestors={"footer"}))

        overridden = css + "\np a, .footer a { text-decoration: none; border-bottom: none; }"
        self.assertFalse(link_has_non_color_cue(overridden, ancestors={"p"}))
        self.assertFalse(link_has_non_color_cue(overridden, ancestors={"footer"}))


class ResponsiveLayoutContractTests(unittest.TestCase):
    def test_outcome_grid_stays_balanced_until_the_mobile_breakpoint(self):
        css = Path("docs/styles.css").read_text(encoding="utf-8")

        self.assertRegex(
            css,
            r"(?m)^\.outcome-grid \{[^\n]*grid-template-columns: repeat\(2, 1fr\);",
        )
        self.assertIn(".outcome-grid article:nth-child(odd) { border-left: 0; }", css)
        self.assertIn(
            ".outcome-grid article:nth-child(n+3) { border-top: 1px solid var(--border); }",
            css,
        )
        self.assertIn(
            "@media (max-width: 980px) {",
            css,
        )
        self.assertIn(
            ".outcome-grid { grid-template-columns: repeat(2, 1fr); }",
            css,
        )
        self.assertIn(
            ".safety-grid, .outcome-grid, .next-paths { grid-template-columns: 1fr; }",
            css,
        )


class PrivacyDataFlowContractTests(unittest.TestCase):
    def setUp(self):
        self.privacy = Path("docs/privacy.html").read_text(encoding="utf-8")
        self.privacy_lower = self.privacy.lower()

    def test_privacy_rejects_stale_universal_absolutes(self):
        stale_claims = (
            "all communication stays between your ai agent and your local unifi controller",
            "there is no web interface",
            "they are never logged, transmitted externally, or stored in any persistent database",
            "unifi mcp stores <strong>nothing</strong>",
            "there is no database, no cache, no log files, and no session state",
        )

        for claim in stale_claims:
            with self.subTest(claim=claim):
                self.assertNotIn(claim, self.privacy_lower)

    def test_privacy_describes_api_operator_controlled_persistence(self):
        required = (
            "unifi-api-server",
            "operator-controlled sqlite",
            "encrypted controller credentials",
            "api-key hashes",
            "sessions",
            "audit records",
            "settings",
            "administrative ui",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.privacy_lower)

    def test_privacy_distinguishes_relay_transit_from_persisted_metadata(self):
        required = (
            "tool-call arguments and results pass through cloudflare in transit",
            "durable object sqlite",
            "location metadata",
            "hashed relay tokens",
            "tool catalogs",
            "does not store controller credentials",
            "application code does not persist tool-call arguments or results",
            "cloudflare's own platform logging, retention, and privacy behavior",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.privacy_lower)

    def test_privacy_discloses_documentation_site_requests(self):
        required = (
            "google fonts",
            "github api",
            "pypi",
            "npm registry",
            "standard request metadata",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.privacy_lower)
        self.assertIn("homepage or sponsor page", self.privacy_lower)

    def test_privacy_discloses_trace_export(self):
        required = (
            "otel_exporter_otlp_endpoint",
            "no spans leave the server process",
            "not tool arguments or results",
            "contains the requested resource uri",
            "records the camera id",
            "carries the meta tool's name",
            "stack trace",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, self.privacy_lower)

    def test_privacy_has_current_revision_date(self):
        self.assertIn("Last updated: November 12, 2026", self.privacy)

    def test_privacy_discloses_site_manager_cloud_path(self):
        section = self.privacy.split('<h2 id="site-manager">', 1)[1].split("<h2", 1)[0].lower()
        required = (
            "https://api.ui.com",
            "even when it runs on your machine over local stdio",
            "destination is fixed",
            "account-wide",
            "never taken from, or shared with, the console credentials",
            "does not include this server by default",
        )

        for phrase in required:
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)
        self.assertIn(
            "cloud-backed Site Manager server",
            meta_content(inspect_html(Path("docs/privacy.html")), "name", "description")[0],
        )

    def test_repository_privacy_policy_matches_the_site_manager_path(self):
        policy = Path("PRIVACY.md").read_text(encoding="utf-8")
        section = policy.split("### Site Manager cloud requests", 1)[1].split("\n### ", 1)[0]
        self.assertNotIn("All communication stays between your AI agent and your local UniFi controller", policy)
        for phrase in (
            "https://api.ui.com",
            "local stdio",
            "fixed in the code",
            "account-wide",
            "never taken from, or shared with",
            "does not include this server by default",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_privacy_names_only_supported_retention_controls(self):
        self.assertNotIn("delete relay locations", self.privacy_lower)
        self.assertNotIn("operator-controlled logs", self.privacy_lower)
        self.assertIn("local sqlite state and any configured logs", self.privacy_lower)
        self.assertIn("rotate relay tokens", self.privacy_lower)
        self.assertIn("destroy the worker deployment", self.privacy_lower)


class CapabilityAndDiscoveryTests(unittest.TestCase):
    def test_homepage_product_tool_counts_match_manifests(self):
        parser = inspect_html(Path("docs/index.html"))
        product_elements = {
            attributes.get("data-product"): attributes.get("data-tool-count")
            for _, attributes in parser.start_tags
            if "data-product" in attributes
        }
        for product, count in manifest_counts().items():
            if product == "innerspace" and not INNERSPACE_RELEASED:
                continue  # the homepage lists released servers only
            with self.subTest(product=product):
                self.assertIn(product, product_elements)
                self.assertEqual(product_elements[product], str(count))

    def test_discovery_files_exist(self):
        for path in DISCOVERY_FILES:
            with self.subTest(path=path):
                self.assertTrue(path.is_file(), f"Missing discovery file: {path}")

    def test_all_local_html_links_and_fragments_resolve(self):
        for source, page_url in LINKED_HTML_PAGES.items():
            parser = inspect_html(source)
            for href in parser.links:
                with self.subTest(source=source, href=href):
                    resolved = urljoin(page_url, href)
                    parsed = urlparse(resolved)
                    if parsed.scheme == "mailto":
                        continue
                    if parsed.scheme not in {"http", "https"}:
                        self.fail(f"Unsupported link scheme in {source}: {href}")
                    if f"{parsed.scheme}://{parsed.netloc}" != SITE_ORIGIN:
                        continue

                    target = site_url_to_path(resolved)
                    self.assertTrue(target.is_file(), f"Local link does not resolve: {href} -> {target}")
                    if parsed.fragment and target.suffix == ".html":
                        target_parser = inspect_html(target)
                        self.assertIn(
                            unquote(parsed.fragment),
                            target_parser.ids,
                            f"Fragment does not exist: {href} -> {target}",
                        )

    def test_404_uses_root_relative_shared_assets_for_nested_missing_routes(self):
        parser = inspect_html(Path("docs/404.html"))
        links = parser.attributes_for("link")
        favicon_urls = [
            attributes.get("href", "") for attributes in links if "icon" in attributes.get("rel", "").split()
        ]
        stylesheet_urls = [
            attributes.get("href", "")
            for attributes in links
            if "stylesheet" in attributes.get("rel", "").split()
            and attributes.get("href", "") in {"styles.css", "/styles.css"}
        ]

        self.assertEqual(favicon_urls, ["/assets/favicon.svg"])
        self.assertEqual(stylesheet_urls, ["/styles.css"])
        self.assertNotIn("assets/favicon.svg", favicon_urls)
        self.assertNotIn("styles.css", stylesheet_urls)

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

    def test_robots_has_exact_allow_and_canonical_sitemap_contract(self):
        self.assertEqual(
            Path("docs/robots.txt").read_text(encoding="utf-8"),
            "User-agent: *\nAllow: /\n\nSitemap: https://unifimcp.com/sitemap.xml\n",
        )

    def test_404_is_noindex_and_excluded_from_sitemap(self):
        parser = inspect_html(Path("docs/404.html"))
        robots = meta_content(parser, "name", "robots")
        self.assertEqual(len(robots), 1)
        self.assertIn("noindex", {token.strip().lower() for token in robots[0].split(",")})

        sitemap = Path("docs/sitemap.xml").read_text(encoding="utf-8")
        self.assertNotIn("404", sitemap)

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

    def test_llms_txt_links_resolve_to_site_or_repository_paths(self):
        links = markdown_links(Path("docs/llms.txt").read_text(encoding="utf-8"))
        self.assertGreater(len(links), 0)

        for link in links:
            with self.subTest(link=link):
                parsed = urlparse(link)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                if origin == SITE_ORIGIN:
                    target = site_url_to_path(link)
                    self.assertTrue(target.is_file(), f"Site link does not resolve: {link} -> {target}")
                    if parsed.fragment and target.suffix == ".html":
                        self.assertIn(unquote(parsed.fragment), inspect_html(target).ids)
                    continue

                if link.rstrip("/") == REPOSITORY_URL:
                    continue

                repository_match = re.fullmatch(
                    r"https://github\.com/sirkirby/unifi-mcp/(blob|tree)/main/([^?#]+)(?:[?#].*)?",
                    link,
                )
                if repository_match:
                    kind, repository_path = repository_match.groups()
                    target = Path(unquote(repository_path))
                    if kind == "blob":
                        self.assertTrue(target.is_file(), f"Repository file link does not resolve: {link}")
                    else:
                        self.assertTrue(target.is_dir(), f"Repository directory link does not resolve: {link}")
                    continue

                if parsed.netloc in {"unifimcp.com", "github.com"}:
                    self.fail(f"Unrecognized project-owned link: {link}")

    def test_sponsor_loads_shared_star_enhancement_without_version_targets(self):
        sponsor = inspect_html(Path("docs/sponsor/index.html"))
        scripts = sponsor.attributes_for("script")
        shared_scripts = [attributes for attributes in scripts if attributes.get("src") == "../app.js"]
        self.assertEqual(len(shared_scripts), 1)
        self.assertIn("defer", shared_scripts[0])

        app = Path("docs/app.js").read_text(encoding="utf-8")
        self.assertIn("fetchJSON('/data/project-stats.json')", app)
        self.assertIn(
            "if (!document.querySelector('[data-pkg-version], [data-npm-version]')) return;",
            app,
        )

    def test_footers_link_every_published_mcp_server(self):
        servers = (
            ["Network", "Protect", "Access"]
            + (["Site Manager"] if SITEMANAGER_RELEASED else [])
            + (["InnerSpace"] if INNERSPACE_RELEASED else [])
            + ["Drive"]
        )
        for path in (Path("docs/index.html"), Path("docs/404.html"), Path("docs/sponsor/index.html")):
            html = path.read_text(encoding="utf-8")
            footer = html.split("<h2>MCP servers</h2>", 1)[1].split("</div>", 1)[0]
            with self.subTest(path=path):
                self.assertEqual(re.findall(r'<a href="https://pypi\.org/project/[^"]+/">([^<]+)</a>', footer), servers)

    def test_app_js_package_lists_include_every_published_python_server(self):
        app = Path("docs/app.js").read_text(encoding="utf-8")
        expected = re.search(r"var EXPECTED_PACKAGE_NAMES = \[(.*?)\];", app, flags=re.DOTALL).group(1)
        refreshed = re.search(r"var pythonPackages = \[(.*?)\];", app, flags=re.DOTALL).group(1)
        expected_names = re.findall(r"'([^']+)'", expected)
        refreshed_names = re.findall(r"'([^']+)'", refreshed)

        self.assertEqual(expected_names, sorted(expected_names))
        self.assertEqual(set(expected_names), set(refreshed_names))
        for name in MCP_SERVER_LINKS:
            with self.subTest(package=name):
                self.assertEqual(name in expected_names, SITEMANAGER_RELEASED or name != "unifi-sitemanager-mcp")

    def test_app_js_tolerates_exactly_the_packages_the_snapshot_lacks(self):
        app = Path("docs/app.js").read_text(encoding="utf-8")
        expected = re.search(r"var EXPECTED_PACKAGE_NAMES = \[(.*?)\];", app, flags=re.DOTALL).group(1)
        awaiting = re.search(r"var AWAITING_FIRST_STATS = \[(.*?)\];", app, flags=re.DOTALL).group(1)
        expected_names = set(re.findall(r"'([^']+)'", expected))
        awaiting_names = set(re.findall(r"'([^']+)'", awaiting))
        snapshot = json.loads(Path("docs/data/project-stats.json").read_text(encoding="utf-8"))

        for section in ("python", "containers"):
            with self.subTest(section=section):
                self.assertEqual(expected_names - set(snapshot[section]["packages"]), awaiting_names)

    def test_star_fallbacks_match_the_checked_in_snapshot(self):
        snapshot = json.loads(Path("docs/data/project-stats.json").read_text(encoding="utf-8"))
        expected = f"★ {snapshot['github']['stars']:,}"

        for path in (Path("docs/index.html"), Path("docs/sponsor/index.html")):
            with self.subTest(path=path):
                html = path.read_text(encoding="utf-8")
                fallback = re.findall(r"<span data-stars>([^<]*)</span>", html)
                self.assertEqual(fallback, [expected])


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
                    self.assertTrue(
                        states_count(content, counts[product]),
                        f"{path} must state the current {product} tool count ({counts[product]})",
                    )

    def test_plugin_count_surfaces_match_the_pinned_server(self):
        counts = pinned_counts()
        for product, paths in PLUGIN_COUNT_SURFACES.items():
            for path in paths:
                with self.subTest(product=product, path=path):
                    content = path.read_text(encoding="utf-8")
                    self.assertTrue(
                        states_count(content, counts[product]),
                        f"{path} must state the tool count of the {product} release its plugin pins "
                        f"({counts[product]})",
                    )

    def test_network_traffic_route_catalog_matches_manifest(self):
        manifest = json.loads(MANIFESTS["network"].read_text(encoding="utf-8"))
        expected = [
            tool["name"]
            for tool in manifest["tools"]
            if manifest["module_map"].get(tool["name"]) == "unifi_network_mcp.tools.traffic_routes"
        ]
        content = Path("apps/network/docs/tools.md").read_text(encoding="utf-8")
        section = content.split("## Traffic Routes", maxsplit=1)[1].split("\n## ", maxsplit=1)[0]
        heading = f"## Traffic Routes{section.splitlines()[0]}"

        self.assertEqual(heading, f"## Traffic Routes ({len(expected)} tools)")
        self.assertCountEqual(re.findall(r"`(unifi_[a-z0-9_]+)`", section), expected)

    def test_server_status_table_matches_manifests_and_current_stability(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        homepage = Path("docs/index.html").read_text(encoding="utf-8")
        counts = manifest_counts()

        for product in ("Network", "Protect", "Access"):
            with self.subTest(product=product):
                self.assertRegex(
                    readme,
                    rf"\| \[{product}\][^\n]*\| Stable \| {counts[product.lower()]} \|",
                )

        status = "Beta" if SITEMANAGER_RELEASED else "Not yet released"
        self.assertIn(
            f"| [Site Manager](apps/sitemanager/) | {status} | {counts['sitemanager']} |",
            readme,
        )
        self.assertIn(f"<h4>Site Manager <span>{status}</span></h4>", homepage)

        for product in ("Protect", "Access"):
            with self.subTest(product=product):
                self.assertIn(f"<h4>{product} <span>Stable</span></h4>", homepage)
                self.assertNotRegex(homepage, rf"<h4>{product} <span>Beta</span></h4>")

    def test_readme_and_homepage_link_all_non_server_products(self):
        surfaces = {
            Path("README.md"): Path("README.md").read_text(encoding="utf-8"),
            Path("docs/index.html"): Path("docs/index.html").read_text(encoding="utf-8"),
        }
        for path, content in surfaces.items():
            for product, url in PRODUCT_LINKS.items():
                with self.subTest(path=path, product=product):
                    self.assertIn(url, content)

    def test_discovery_docs_route_custom_apps_and_mcp_adapters_to_api(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        chooser = readme.split("## Choose an integration", 1)[1].split("\n## ", 1)[0]
        api_section = readme.split("## REST + GraphQL API", 1)[1].split("\n## ", 1)[0]

        self.assertRegex(
            chooser,
            r"(?is)custom application.*MCP adapter.*unifi-api-server",
        )
        self.assertRegex(chooser, r"(?is)MCP adapter.*expose.*tools.*backend")
        self.assertIn("independent HTTP service", api_section)
        self.assertIn("does not proxy or require them", api_section)

        discovery_docs = {
            Path("apps/api/README.md"): Path("apps/api/README.md").read_text(encoding="utf-8"),
            Path("QUICKSTART.md"): Path("QUICKSTART.md").read_text(encoding="utf-8"),
            Path("docs/index.html"): Path("docs/index.html").read_text(encoding="utf-8"),
            Path("docs/llms.txt"): Path("docs/llms.txt").read_text(encoding="utf-8"),
        }
        for path, content in discovery_docs.items():
            with self.subTest(path=path):
                self.assertIn("MCP adapter", content)
                self.assertNotRegex(content, r"(?i)non-MCP|without speaking MCP")

        for product in ("network", "protect", "access"):
            product_readme = Path(f"apps/{product}/README.md").read_text(encoding="utf-8")
            with self.subTest(product=product):
                self.assertIn("MCP-capable", product_readme)
                self.assertIn("unifi-api-server", product_readme)

        tool_index = Path("docs/tool-index.md").read_text(encoding="utf-8")
        normalized_tool_index = " ".join(tool_index.split())
        self.assertRegex(
            normalized_tool_index,
            r"custom application, code-execution runtime, or MCP adapter.*unifi-api-server",
        )
        self.assertIn("Existing MCP clients can continue", normalized_tool_index)

    def test_api_orchestration_docs_preserve_interface_and_safety_boundaries(self):
        api_readme = Path("apps/api/README.md").read_text(encoding="utf-8")
        section = api_readme.split("### Custom orchestration and MCP adapters", 1)[1].split("\n### ", 1)[0]
        normalized_section = " ".join(section.split())

        self.assertIn("GraphQL for typed, paginated reads", normalized_section)
        self.assertIn("field selection", normalized_section)
        self.assertIn("REST for typed resource reads", normalized_section)
        self.assertIn('`"confirm": false`', normalized_section)
        self.assertIn('`"confirm": true`', normalized_section)
        self.assertIn("resend the same body", normalized_section)
        self.assertIn("does not sandbox generated code", normalized_section)
        self.assertIn("The application must enforce those limits", normalized_section)

        examples = Path("examples/README.md").read_text(encoding="utf-8")
        normalized_examples = " ".join(examples.split())
        self.assertNotIn("server's code-execution features", examples)
        self.assertIn("Code-based processing runs in the calling client", normalized_examples)
        self.assertIn("(direct MCP", examples)

    def test_worker_readme_uses_current_relay_contract(self):
        readme = Path("apps/worker/README.md").read_text(encoding="utf-8")
        self.assertIn("UNIFI_RELAY_TOKEN", readme)
        self.assertNotIn("UNIFI_MCP_RELAY_TOKEN", readme)
        self.assertRegex(readme, r"(?i)relay[^\n]*(?:MCP over HTTP|MCP HTTP)")
        self.assertNotRegex(readme, r"(?i)relay[^\n]*stdio")

    def test_relay_architecture_names_shared_dependencies_and_excludes_server_apps(self):
        architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
        relay_section = architecture.split("### packages/unifi-mcp-relay", 1)[1].split("\n### ", 1)[0]

        self.assertNotIn("`unifi-core`, `unifi-mcp-shared`, or any `apps/*`", relay_section)
        self.assertIn("`unifi-mcp-shared`", relay_section)
        self.assertIn("`unifi-core`", relay_section)
        self.assertRegex(relay_section, r"(?i)does not[^\n]*(?:import|depend)[^\n]*server app packages")

    def test_site_manager_server_row_uses_its_colour_and_release_state(self):
        parser = inspect_html(Path("docs/index.html"))
        rows = [
            attributes
            for attributes in parser.attributes_for("div")
            if "server-row" in attributes.get("class", "").split()
        ]
        expected = (
            ["network", "protect", "access", "sitemanager"]
            + (["innerspace"] if INNERSPACE_RELEASED else [])
            + ["drive"]
        )
        self.assertEqual([row["data-product"] for row in rows], expected)
        by_product = {row["data-product"]: row for row in rows}
        self.assertIn("sitemanager", by_product["sitemanager"]["class"].split())
        self.assertEqual(
            by_product["sitemanager"]["data-release"], "released" if SITEMANAGER_RELEASED else "unreleased"
        )

        css = Path("docs/styles.css").read_text(encoding="utf-8")
        self.assertRegex(css, r"(?m)^  --sitemanager: #7C5CFF;$")
        self.assertIn(".server-row.sitemanager::before { background: var(--sitemanager); }", css)
        if INNERSPACE_RELEASED:
            self.assertIn("innerspace", by_product["innerspace"]["class"].split())
            self.assertEqual(by_product["innerspace"]["data-release"], "released")
            self.assertIn(".server-row.innerspace::before { background: var(--innerspace); }", css)
        self.assertIn("drive", by_product["drive"]["class"].split())
        self.assertEqual(by_product["drive"]["data-release"], "released")
        self.assertIn(".server-row.drive::before { background: var(--drive); }", css)
        mobile = css.split("@media (max-width: 760px) {", 1)[1].split("\n}", 1)[0]
        self.assertIn(".server-row { grid-template-columns: 1fr; gap: 12px; }", mobile)

    def test_landing_page_keeps_three_product_paths(self):
        homepage = Path("docs/index.html").read_text(encoding="utf-8")
        self.assertIn("<h2>Three product paths, built for different jobs.</h2>", homepage)
        self.assertEqual(homepage.count('class="product-number"'), 3)

    def test_unreleased_site_manager_is_not_presented_as_installable(self):
        if SITEMANAGER_RELEASED:
            self.skipTest("unifi-sitemanager-mcp is released")
        for path in SERVER_SURFACES:
            content = path.read_text(encoding="utf-8")
            for text in SITEMANAGER_RELEASE_ONLY_TEXT:
                with self.subTest(path=path, text=text):
                    self.assertNotIn(text, content)

    def test_released_site_manager_install_surfaces_are_present(self):
        if not SITEMANAGER_RELEASED:
            self.skipTest("unifi-sitemanager-mcp is not released")
        expected = {
            Path("README.md"): (
                "img.shields.io/pypi/v/unifi-sitemanager-mcp",
                "uvx unifi-sitemanager-mcp@latest",
                "unifi-sitemanager@unifi-plugins",
            ),
            Path("QUICKSTART.md"): ("uvx unifi-sitemanager-mcp@latest", "unifi-sitemanager@unifi-plugins"),
            Path("SECURITY.md"): ("| unifi-sitemanager-mcp | Latest release (beta) |",),
            Path("docs/index.html"): (
                'uvx <span class="value">unifi-sitemanager-mcp@latest</span>',
                'pipx install <span class="value">unifi-sitemanager-mcp</span>',
                '<a href="https://pypi.org/project/unifi-sitemanager-mcp/">Site Manager</a>',
            ),
        }
        for path, phrases in expected.items():
            content = path.read_text(encoding="utf-8")
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)
            with self.subTest(path=path):
                self.assertNotRegex(content, r"(?i)site manager[^\n]*not (?:yet )?(?:published|released)")

    def test_console_credentials_follow_the_host_where_precedence_is_described(self):
        warning = "is set but not used: the host comes from UNIFI_{p}_HOST, which differs from UNIFI_HOST"
        surfaces = {
            Path("docs/credential-providers.md"): ("### Credentials follow the host", warning.format(p="PROTECT")),
            Path("README.md"): ("Credentials follow the host.", "#credentials-follow-the-host"),
            **{
                Path(f"apps/{app}/docs/configuration.md"): (
                    "**Credentials follow the host.**",
                    warning.format(p=app.upper()),
                )
                for app in ("network", "protect", "access")
            },
        }
        for path, phrases in surfaces.items():
            content = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_site_manager_cloud_boundary_is_stated_where_servers_are_configured(self):
        surfaces = {
            Path("README.md"): ("https://api.ui.com", "UNIFI_SITEMANAGER_API_KEY", "no shared fallback"),
            Path("QUICKSTART.md"): ("https://api.ui.com", "even when your client runs", "port 3003"),
            Path("SECURITY.md"): ("https://api.ui.com", "cannot be changed", "never sent to a console"),
            Path(".env.example"): (
                "UNIFI_SITEMANAGER_API_KEY_FILE",
                "UNIFI_SITEMANAGER_API_KEY_COMMAND",
                "Set exactly one",
            ),
            Path("docs/credential-providers.md"): ("No shared fallback", "`UNIFI_API_KEY`", "exactly one"),
            Path("docs/tls-verification.md"): ("Site Manager", "always verifies"),
            Path("apps/network/docs/transports.md"): (
                "Site Manager (port 3003)",
                "UNIFI_SITEMANAGER_MCP_HTTP_AUTH_TOKEN",
            ),
        }
        for path, phrases in surfaces.items():
            content = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_relay_stays_opt_in_for_site_manager(self):
        surfaces = (
            Path("README.md"),
            Path("QUICKSTART.md"),
            Path("SECURITY.md"),
            Path("PRIVACY.md"),
            Path(".env.example"),
            Path("docs/privacy.html"),
            Path("docs/cross-product.md"),
            Path("apps/network/docs/transports.md"),
        )
        for path in surfaces:
            content = " ".join(path.read_text(encoding="utf-8").split()).lower()
            with self.subTest(path=path):
                self.assertRegex(content, r"relay does not (?:include|reach) [^.]*?(?:unless|by default)")
                self.assertRegex(content, r"read the whole (?:ui |cloud )?account")

    def test_api_readme_documents_every_site_manager_route(self):
        spec = json.loads(Path("apps/api/openapi.json").read_text(encoding="utf-8"))
        paths = sorted(path for path in spec["paths"] if path.startswith("/v1/sitemanager/"))
        self.assertGreater(len(paths), 0)
        readme = Path("apps/api/README.md").read_text(encoding="utf-8")
        section = readme.split("## Site Manager cloud connection", 1)[1].split("\n## ", 1)[0]
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, section)
        for phrase in (
            "unifi-api-server sitemanager add",
            "--key-stdin",
            "unifi-api-server sitemanager update --rotate-key",
            "unifi-api-server sitemanager probe",
            "unifi-api-server sitemanager delete",
            "/admin/sitemanager",
            "The `sitemanager` namespace",
            "`admin` scope",
            "`read` scope",
            "can read the whole UI account",
            "`503` `sitemanager_not_configured`",
            "NOT_CONFIGURED",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_server_status_table_lists_innerspace_with_its_release_state(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        status = "Beta" if INNERSPACE_RELEASED else "Not yet released"
        self.assertIn(f"| [InnerSpace](apps/innerspace/) | {status} | {manifest_counts()['innerspace']} |", readme)

    def test_unreleased_innerspace_is_not_presented_as_installable(self):
        if INNERSPACE_RELEASED:
            self.skipTest("unifi-innerspace-mcp is released")
        for path in SERVER_SURFACES + INNERSPACE_APP_PAGES:
            content = path.read_text(encoding="utf-8")
            for text in INNERSPACE_RELEASE_ONLY_TEXT:
                with self.subTest(path=path, text=text):
                    self.assertNotIn(text, content)

    def test_innerspace_is_named_as_not_yet_released_on_the_pages_that_list_servers(self):
        if INNERSPACE_RELEASED:
            self.skipTest("unifi-innerspace-mcp is released")
        for path in (
            Path("README.md"),
            Path("QUICKSTART.md"),
            Path("docs/README.md"),
            Path("docs/ARCHITECTURE.md"),
            Path("apps/innerspace/README.md"),
        ):
            content = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(path=path):
                self.assertRegex(content, r"(?i)innerspace[^.|]*(?:not (?:yet )?(?:published|released)|unreleased)")

    def test_released_innerspace_install_surfaces_are_present(self):
        if not INNERSPACE_RELEASED:
            self.skipTest("unifi-innerspace-mcp is not released")
        expected = {
            Path("README.md"): ("img.shields.io/pypi/v/unifi-innerspace-mcp", "uvx unifi-innerspace-mcp@latest"),
            Path("QUICKSTART.md"): ("uvx unifi-innerspace-mcp@latest",),
            Path("SECURITY.md"): ("| unifi-innerspace-mcp | Latest release (beta) |",),
            Path("apps/innerspace/README.md"): (
                "pypi.org/project/unifi-innerspace-mcp",
                "pip install unifi-innerspace-mcp",
                "docker pull ghcr.io/sirkirby/unifi-innerspace-mcp",
            ),
            Path("docs/index.html"): (
                'uvx <span class="value">unifi-innerspace-mcp@latest</span>',
                'pipx install <span class="value">unifi-innerspace-mcp</span>',
                '<a href="https://pypi.org/project/unifi-innerspace-mcp/">InnerSpace</a>',
            ),
        }
        for path, phrases in expected.items():
            content = path.read_text(encoding="utf-8")
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)
        for path in SERVER_SURFACES + INNERSPACE_APP_PAGES:
            content = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(path=path):
                self.assertNotRegex(content, r"(?i)innerspace[^.|]*not (?:yet )?(?:published|released)")
                # No plugin bundle exists yet; drop this check when one ships.
                self.assertNotIn("unifi-innerspace@unifi-plugins", content)

    def test_innerspace_is_listed_where_the_products_are_enumerated(self):
        surfaces = {
            Path("README.md"): ("unifi-innerspace-mcp", "apps/innerspace/docs/configuration.md", "InnerSpace"),
            Path("QUICKSTART.md"): ("InnerSpace", "unifi-innerspace-mcp", "port 3005"),
            Path("CONTRIBUTING.md"): ("apps/innerspace/", "innerspace/v*", "apps/innerspace/docs/troubleshooting.md"),
            Path("SECURITY.md"): ("InnerSpace", "session", "UNIFI_API_KEY"),
            Path("SUPPORT.md"): ("apps/innerspace/docs/troubleshooting.md", "InnerSpace"),
            Path("PRIVACY.md"): ("InnerSpace", "floor plan"),
            Path("docs/README.md"): ("apps/innerspace/docs/configuration.md", "apps/innerspace/docs/tools.md"),
            Path("docs/ARCHITECTURE.md"): ("apps/innerspace", "unifi_core.innerspace"),
            Path("docs/tool-index.md"): ("`innerspace_`", "InnerSpace differences"),
            Path("docs/tls-verification.md"): ("InnerSpace", "UNIFI_INNERSPACE_SSL_FINGERPRINT"),
            Path("docs/permissions.md"): ("InnerSpace", "UNIFI_POLICY_INNERSPACE_<CATEGORY>_<ACTION>"),
            Path("docs/cross-product.md"): ("InnerSpace", "own family"),
            Path("docs/support-bundles.md"): ("InnerSpace", "no support-bundle"),
            Path("apps/api/README.md"): ("## InnerSpace console product", "innerspace_site_id"),
        }
        for path, phrases in surfaces.items():
            content = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_innerspace_docs_scope_the_read_only_annotation_to_the_read_tools(self):
        shared = Path("docs/permissions.md").read_text(encoding="utf-8")
        shared_section = (
            shared.split("### InnerSpace: reads and gated writes", 1)[1].split("\n### ", 1)[0].split("\n---", 1)[0]
        )
        pages = {
            Path("apps/innerspace/README.md"): Path("apps/innerspace/README.md").read_text(encoding="utf-8"),
            Path("apps/innerspace/docs/permissions.md"): Path("apps/innerspace/docs/permissions.md").read_text(
                encoding="utf-8"
            ),
            Path("docs/permissions.md"): shared_section,
        }
        for path, text in pages.items():
            content = " ".join(text.split())
            with self.subTest(path=path):
                self.assertRegex(content, r"(?i)nine read")
                self.assertRegex(content, r"15 writes?\b|15 write tools")
                self.assertNotRegex(content, r"(?i)every tool[^.]*\bread-only|all (?:the )?tools[^.]*\bread-only")
                self.assertNotRegex(content, r"(?i)\bno write tools?\b|registers no write")

    def test_innerspace_docs_state_what_is_and_is_not_redacted_or_served(self):
        tools = " ".join(Path("apps/innerspace/docs/tools.md").read_text(encoding="utf-8").split())
        permissions = " ".join(Path("apps/innerspace/docs/permissions.md").read_text(encoding="utf-8").split())
        self.assertIn("MAC addresses are not redacted", permissions)
        self.assertIn("redacted by default", permissions)
        self.assertNotRegex(permissions, r"(?i)always redacted")
        self.assertIn("image_offset", tools)
        self.assertIn("innerspace://plans/{plan_id}/image", tools)
        self.assertIn("innerspace://plans/{plan_id}/image.jpg", tools)
        self.assertNotIn("include_image", tools)
        self.assertIn(
            "never returns image bytes", " ".join(Path("apps/api/README.md").read_text(encoding="utf-8").split())
        )

    def test_innerspace_not_applied_is_documented_as_a_refusal(self):
        """``mutation_applied: false`` needs the console to refuse the write; anything uncertain is unknown."""
        tools = " ".join(Path("apps/innerspace/docs/tools.md").read_text(encoding="utf-8").split())
        row = next(line for line in tools.split("| `false` | `false` |")[1:2])
        self.assertIn("refused", row.split("|")[0])
        trouble = Path("apps/innerspace/docs/troubleshooting.md").read_text(encoding="utf-8")
        section = trouble.split("### `success: false` with `mutation_applied: false`", 1)[1].split("###", 1)[0]
        self.assertIn("refused", section)
        self.assertIn("time budget", row.split("|")[0])
        self.assertIn("time budget ran out before the change was sent", trouble)

    def test_api_readme_documents_every_innerspace_route(self):
        spec = json.loads(Path("apps/api/openapi.json").read_text(encoding="utf-8"))
        paths = sorted(path for path in spec["paths"] if "/innerspace/" in path)
        self.assertGreater(len(paths), 0)
        readme = Path("apps/api/README.md").read_text(encoding="utf-8")
        section = " ".join(readme.split("## InnerSpace console product", 1)[1].split("\n## ", 1)[0].split())
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, section)
        for phrase in (
            "`innerspace`",
            "username and password",
            "innerspace://plans/{plan_id}/image.jpg",
            "BAD_REQUEST",
            "UPSTREAM_ERROR",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_api_readme_documents_every_drive_route(self):
        spec = json.loads(Path("apps/api/openapi.json").read_text(encoding="utf-8"))
        paths = sorted(path for path in spec["paths"] if "/drive/" in path)
        self.assertEqual(len(paths), 18)
        readme = Path("apps/api/README.md").read_text(encoding="utf-8")
        section = " ".join(readme.split("## UniFi Drive console product", 1)[1].split("\n## ", 1)[0].split())
        for path in paths:
            with self.subTest(path=path):
                self.assertIn(path, section)
        for phrase in (
            "`drive`",
            "username and password",
            "mutation_applied: false",
            "mutation_applied: null",
            "UNIFI_DRIVE_READ_ONLY",
            "drive_set_file_service",
            "drive_remove_nfs_connection",
            "Turning SMB off also turns Time Machine off",
            "BAD_REQUEST",
        ):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, section)

    def test_server_status_table_lists_drive_as_released(self):
        readme = Path("README.md").read_text(encoding="utf-8")
        homepage = Path("docs/index.html").read_text(encoding="utf-8")
        count = manifest_counts()["drive"]
        self.assertIn(
            f"| [Drive](apps/drive/) | Beta | {count} | "
            "[`unifi-drive-mcp`](https://pypi.org/project/unifi-drive-mcp/) |",
            readme,
        )
        self.assertIn("<h4>Drive <span>Beta</span></h4>", homepage)

    def test_released_drive_install_surfaces_are_present(self):
        expected = {
            Path("README.md"): (
                "img.shields.io/pypi/v/unifi-drive-mcp",
                "uvx unifi-drive-mcp@latest",
                "unifi-drive@unifi-plugins",
                "| `unifi-drive` |",
            ),
            Path("QUICKSTART.md"): ("uvx unifi-drive-mcp@latest", "unifi-drive@unifi-plugins"),
            Path("SECURITY.md"): ("| unifi-drive-mcp | Latest release (beta) |",),
            Path("apps/drive/README.md"): (
                "pypi.org/project/unifi-drive-mcp",
                "pip install unifi-drive-mcp",
                "docker pull ghcr.io/sirkirby/unifi-drive-mcp",
                "unifi-drive@unifi-plugins",
            ),
            Path("docs/index.html"): (
                'uvx <span class="value">unifi-drive-mcp@latest</span>',
                'pipx install <span class="value">unifi-drive-mcp</span>',
                '<a href="https://pypi.org/project/unifi-drive-mcp/">Drive</a>',
            ),
        }
        for path, phrases in expected.items():
            content = path.read_text(encoding="utf-8")
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)
        for path in SERVER_SURFACES + DRIVE_APP_PAGES:
            content = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(path=path):
                self.assertNotRegex(content, r"(?i)drive[^.|]*not (?:yet )?(?:published|released)")

    def test_drive_is_listed_where_the_products_are_enumerated(self):
        surfaces = {
            Path("README.md"): ("unifi-drive-mcp", "apps/drive/docs/configuration.md", "port 3004"),
            Path("QUICKSTART.md"): ("Drive", "unifi-drive-mcp", "port 3004"),
            Path("CONTRIBUTING.md"): ("apps/drive/", "drive/v*", "apps/drive/docs/troubleshooting.md"),
            Path("SECURITY.md"): ("UniFi Drive NAS Login", "UNIFI_DRIVE_SSL_FINGERPRINT", "port 3004"),
            Path("SUPPORT.md"): ("apps/drive/docs/troubleshooting.md", "Drive"),
            Path("PRIVACY.md"): ("UniFi Drive storage data", "file contents"),
            Path(".env.example"): ("UNIFI_DRIVE_HOST", "UNIFI_DRIVE_PASSWORD_FILE", "port 3004"),
            Path("docs/README.md"): ("apps/drive/docs/configuration.md", "apps/drive/docs/tools.md"),
            Path("docs/ARCHITECTURE.md"): ("apps/drive", "unifi_core.drive"),
            Path("docs/llms.txt"): ("apps/drive/README.md", "port 3004"),
            Path("docs/tool-index.md"): ("`drive_`", "Drive differences"),
            Path("docs/tls-verification.md"): ("Drive", "UNIFI_DRIVE_SSL_FINGERPRINT", "no shared fallback"),
            Path("docs/permissions.md"): ("Drive", "UNIFI_POLICY_DRIVE_NFS_CONNECTIONS_DELETE"),
            Path("docs/cross-product.md"): ("Drive is its own family",),
            Path("docs/support-bundles.md"): ("Drive", "no support-bundle"),
            Path("docs/credential-providers.md"): ("UNIFI_DRIVE_*", "never fall back"),
            Path("docs/agent-install.md"): ("## Drive (UniFi NAS)", "| Drive | `unifi-drive` |"),
            Path("apps/network/docs/transports.md"): ("Drive (port 3004)", "UNIFI_DRIVE_MCP_HTTP_AUTH_TOKEN"),
        }
        for path, phrases in surfaces.items():
            content = " ".join(path.read_text(encoding="utf-8").split())
            for phrase in phrases:
                with self.subTest(path=path, phrase=phrase):
                    self.assertIn(phrase, content)

    def test_drive_docs_state_its_isolated_login_and_time_machine_coupling(self):
        for path in (Path("apps/drive/README.md"), Path("apps/drive/docs/configuration.md")):
            content = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(path=path):
                for name in (
                    "UNIFI_HOST",
                    "UNIFI_USERNAME",
                    "UNIFI_PASSWORD",
                    "UNIFI_DRIVE_MCP_HTTP_AUTH_TRUSTED_NETWORKS",
                ):
                    self.assertIn(name, content)
                self.assertRegex(content, r"(?i)no request at startup")
        for path in (Path("QUICKSTART.md"), Path("apps/drive/docs/permissions.md")):
            content = " ".join(path.read_text(encoding="utf-8").split())
            with self.subTest(path=path):
                self.assertRegex(content, r"(?i)turning SMB off[^.]*turns Time Machine off")
        support = " ".join(Path("docs/support-bundles.md").read_text(encoding="utf-8").split())
        self.assertRegex(
            support, r"Drive server has no support-bundle tool[^.]*\. The bundle is one closed privacy schema"
        )

    def test_public_pages_do_not_make_outdated_claims(self):
        for path in PUBLIC_PAGES:
            content = path.read_text(encoding="utf-8")
            for claim in FORBIDDEN_PUBLIC_CLAIMS:
                with self.subTest(path=path, claim=claim):
                    self.assertNotIn(claim, content)


if __name__ == "__main__":
    unittest.main()
