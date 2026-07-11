from __future__ import annotations

import json
import re
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
        self.assertEqual(len(has_part), len(JSON_LD_PRODUCT_LINKS))
        self.assertTrue(all(isinstance(part, dict) for part in has_part))
        product_links = {part.get("name"): part.get("url") for part in has_part}
        self.assertEqual(product_links, JSON_LD_PRODUCT_LINKS)


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

    def test_privacy_has_current_revision_date(self):
        self.assertIn("Last updated: July 10, 2026", self.privacy)

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

    def test_relay_architecture_names_shared_dependencies_and_excludes_server_apps(self):
        architecture = Path("docs/ARCHITECTURE.md").read_text(encoding="utf-8")
        relay_section = architecture.split("### packages/unifi-mcp-relay", 1)[1].split("\n### ", 1)[0]

        self.assertNotIn("`unifi-core`, `unifi-mcp-shared`, or any `apps/*`", relay_section)
        self.assertIn("`unifi-mcp-shared`", relay_section)
        self.assertIn("`unifi-core`", relay_section)
        self.assertRegex(relay_section, r"(?i)does not[^\n]*(?:import|depend)[^\n]*server app packages")

    def test_public_pages_do_not_make_outdated_claims(self):
        for path in PUBLIC_PAGES:
            content = path.read_text(encoding="utf-8")
            for claim in FORBIDDEN_PUBLIC_CLAIMS:
                with self.subTest(path=path, claim=claim):
                    self.assertNotIn(claim, content)


if __name__ == "__main__":
    unittest.main()
