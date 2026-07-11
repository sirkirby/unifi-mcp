from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from email.message import Message
from pathlib import Path
from typing import Any
from unittest import mock
from urllib.error import HTTPError
from urllib.request import Request

SCRIPT_PATH = Path(__file__).parents[2] / "scripts" / "update_docs_stats.py"
SPEC = importlib.util.spec_from_file_location("update_docs_stats", SCRIPT_PATH)
if SPEC is None or SPEC.loader is None:
    raise RuntimeError(f"Unable to load collector from {SCRIPT_PATH}")
stats = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(stats)


class FixtureClient:
    def __init__(
        self,
        *,
        pypi: dict[str, int],
        ghcr: dict[str, int],
        stars: int,
        starred_at: list[str],
        pull_requests: list[dict[str, Any]],
        npm_downloads: int,
    ) -> None:
        self._pypi = pypi
        self._ghcr = ghcr
        self._stars = stars
        self._starred_at = starred_at
        self._pull_requests = pull_requests
        self._npm_downloads = npm_downloads

    def pypi_recent(self, name: str) -> int:
        return self._pypi[name]

    def ghcr_package_totals(self, token: str) -> dict[str, int]:
        return self._ghcr

    def repository(self, token: str) -> dict[str, int]:
        return {"stargazers_count": self._stars}

    def stargazers(self, token: str) -> list[str]:
        return self._starred_at

    def merged_pull_requests(self, token: str, cutoff: datetime) -> list[dict[str, Any]]:
        return self._pull_requests

    def npm_downloads(self) -> int:
        return self._npm_downloads


class CollectorContractTests(unittest.TestCase):
    def test_package_map_pairs_all_five_distribution_families(self):
        self.assertEqual(
            stats.PACKAGE_MAP,
            {
                "network": ("unifi-network-mcp", "unifi-network-mcp"),
                "protect": ("unifi-protect-mcp", "unifi-protect-mcp"),
                "access": ("unifi-access-mcp", "unifi-access-mcp"),
                "api": ("unifi-api-server", "unifi-api-server"),
                "relay": ("unifi-mcp-relay", "unifi-mcp-relay"),
            },
        )

    def test_collect_snapshot_keeps_python_and_container_totals_separate(self):
        client = FixtureClient(
            pypi={name: 1_000 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={name: 10_000 for _, name in stats.PACKAGE_MAP.values()},
            stars=509,
            starred_at=["2026-07-01T00:00:00Z"],
            pull_requests=[
                {"user": {"login": "community-user", "type": "User"}},
                {"user": {"login": "dependabot[bot]", "type": "Bot"}},
                {"user": {"login": "sirkirby", "type": "User"}},
            ],
            npm_downloads=834,
        )
        result = stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))
        self.assertEqual(result["python"]["total"], 5_000)
        self.assertEqual(result["python"]["period"], "trailing_30_days")
        self.assertEqual(result["containers"]["total"], 50_000)
        self.assertEqual(result["containers"]["period"], "lifetime")
        self.assertEqual(result["community"]["merged_pull_requests"], 1)
        self.assertEqual(result["community"]["contributors"], 1)

    def test_missing_pypi_package_aborts_collection(self):
        client = FixtureClient(
            pypi={},
            ghcr={name: 1 for _, name in stats.PACKAGE_MAP.values()},
            stars=0,
            starred_at=[],
            pull_requests=[],
            npm_downloads=0,
        )

        with self.assertRaisesRegex(stats.StatsError, "PyPI.*unifi-network-mcp"):
            stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

    def test_missing_ghcr_package_aborts_collection(self):
        client = FixtureClient(
            pypi={name: 1 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={},
            stars=0,
            starred_at=[],
            pull_requests=[],
            npm_downloads=0,
        )

        with self.assertRaisesRegex(stats.StatsError, "GHCR.*unifi-network-mcp"):
            stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

    def test_owner_and_bots_are_excluded_from_community_counts(self):
        client = FixtureClient(
            pypi={name: 1 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={name: 1 for _, name in stats.PACKAGE_MAP.values()},
            stars=0,
            starred_at=[],
            pull_requests=[
                {"user": {"login": "alice", "type": "User"}},
                {"user": {"login": "alice", "type": "User"}},
                {"user": {"login": "sirkirby", "type": "User"}},
                {"user": {"login": "release-bot", "type": "Bot"}},
            ],
            npm_downloads=0,
        )

        result = stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

        self.assertEqual(result["community"]["merged_pull_requests"], 2)
        self.assertEqual(result["community"]["contributors"], 1)

    def test_collect_snapshot_normalizes_malformed_repository_data(self):
        client = FixtureClient(
            pypi={name: 1 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={name: 1 for _, name in stats.PACKAGE_MAP.values()},
            stars="509",
            starred_at=[],
            pull_requests=[],
            npm_downloads=0,
        )

        with self.assertRaisesRegex(stats.StatsError, "GitHub repository"):
            stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

    def test_collect_snapshot_normalizes_malformed_pull_request_user(self):
        client = FixtureClient(
            pypi={name: 1 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={name: 1 for _, name in stats.PACKAGE_MAP.values()},
            stars=0,
            starred_at=[],
            pull_requests=[{"user": None}],
            npm_downloads=0,
        )

        with self.assertRaisesRegex(stats.StatsError, "GitHub merged pull requests.*user"):
            stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

    def test_collect_snapshot_normalizes_malformed_stargazer_timestamp(self):
        client = FixtureClient(
            pypi={name: 1 for name, _ in stats.PACKAGE_MAP.values()},
            ghcr={name: 1 for _, name in stats.PACKAGE_MAP.values()},
            stars=0,
            starred_at=["not-a-timestamp"],
            pull_requests=[],
            npm_downloads=0,
        )

        with self.assertRaisesRegex(stats.StatsError, "GitHub stargazers"):
            stats.collect_snapshot(client, "token", datetime(2026, 7, 10, tzinfo=UTC))

    def test_committed_snapshot_passes_the_canonical_validator(self):
        snapshot_path = Path("docs/data/project-stats.json")
        snapshot = json.loads(snapshot_path.read_text(encoding="utf-8"))

        stats.validate_snapshot(snapshot)


class FakeResponse:
    def __init__(self, payload: Any, headers: Message | None = None) -> None:
        self._payload = json.dumps(payload).encode("utf-8")
        self.headers = headers or Message()

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def read(self) -> bytes:
        return self._payload


class FakeTextResponse(FakeResponse):
    def __init__(self, payload: str, headers: Message | None = None) -> None:
        self._payload = payload.encode("utf-8")
        self.headers = headers or Message()


def pypi_package_page(identity: str, statistics: str) -> str:
    return f"<section><h1>{identity}</h1><hr><p>{statistics}</p></section>"


class JsonClientTests(unittest.TestCase):
    def test_request_json_decodes_utf8_json(self):
        request = Request("https://example.test/data")
        with mock.patch.object(stats, "urlopen", return_value=FakeResponse({"name": "UniFi"})):
            result = stats.request_json(request, source="Example")

        self.assertEqual(result, {"name": "UniFi"})

    def test_request_json_retries_retryable_status_and_honors_retry_after(self):
        headers = Message()
        headers["Retry-After"] = "2"
        failure = HTTPError("https://example.test/data", 429, "rate limited", headers, None)
        request = Request("https://example.test/data")
        with (
            mock.patch.object(
                stats,
                "urlopen",
                side_effect=[failure, FakeResponse({"ok": True})],
            ) as mocked_urlopen,
            mock.patch.object(stats.time, "sleep") as mocked_sleep,
        ):
            result = stats.request_json(request, source="Example")

        self.assertEqual(result, {"ok": True})
        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_sleep.assert_called_once_with(2)

    def test_request_json_does_not_retry_non_retryable_status(self):
        failure = HTTPError("https://example.test/data", 404, "not found", Message(), None)
        request = Request("https://example.test/data")
        with (
            mock.patch.object(stats, "urlopen", side_effect=failure) as mocked_urlopen,
            self.assertRaisesRegex(stats.StatsError, "Example.*404"),
        ):
            stats.request_json(request, source="Example")

        self.assertEqual(mocked_urlopen.call_count, 1)

    def test_request_json_exposes_terminal_http_status_structurally(self):
        failure = HTTPError("https://example.test/data", 429, "rate limited", Message(), None)
        request = Request("https://example.test/data")
        with (
            mock.patch.object(stats, "urlopen", side_effect=failure),
            mock.patch.object(stats.time, "sleep"),
            self.assertRaises(stats.StatsHTTPError) as raised,
        ):
            stats.request_json(request, source="Example")

        self.assertEqual(raised.exception.source, "Example")
        self.assertEqual(raised.exception.status_code, 429)

    def test_request_text_uses_the_same_retry_policy(self):
        failure = HTTPError("https://example.test/page", 503, "unavailable", Message(), None)
        request = Request("https://example.test/page")
        with (
            mock.patch.object(
                stats,
                "urlopen",
                side_effect=[failure, FakeTextResponse("package page")],
            ) as mocked_urlopen,
            mock.patch.object(stats.time, "sleep") as mocked_sleep,
        ):
            result = stats.request_text(request, source="Example page")

        self.assertEqual(result, "package page")
        self.assertEqual(mocked_urlopen.call_count, 2)
        mocked_sleep.assert_called_once_with(1)

    def test_pypi_recent_api_success_does_not_fetch_package_page(self):
        with (
            mock.patch.object(
                stats,
                "request_json",
                return_value={"data": {"last_month": 40_132}},
            ) as mocked_json,
            mock.patch.object(stats, "request_text") as mocked_text,
        ):
            result = stats.JsonClient().pypi_recent("unifi-network-mcp")

        self.assertEqual(result, 40_132)
        mocked_json.assert_called_once()
        mocked_text.assert_not_called()

    def test_pypi_recent_falls_back_to_package_page_after_exhausted_429(self):
        rate_limit = stats.StatsHTTPError("PyPI Stats package unifi-network-mcp", 429)
        html = pypi_package_page(
            "unifi-network-mcp",
            "Downloads last month:\n40,132",
        )
        with (
            mock.patch.object(stats, "request_json", side_effect=rate_limit),
            mock.patch.object(stats, "request_text", return_value=html) as mocked_text,
        ):
            result = stats.JsonClient().pypi_recent("unifi-network-mcp")

        self.assertEqual(result, 40_132)
        request = mocked_text.call_args.args[0]
        self.assertEqual(request.full_url, "https://pypistats.org/packages/unifi-network-mcp")

    def test_pypi_recent_does_not_fallback_for_non_429_http_failure(self):
        unavailable = stats.StatsHTTPError("PyPI Stats package unifi-network-mcp", 503)
        with (
            mock.patch.object(stats, "request_json", side_effect=unavailable),
            mock.patch.object(stats, "request_text") as mocked_text,
            self.assertRaises(stats.StatsHTTPError) as raised,
        ):
            stats.JsonClient().pypi_recent("unifi-network-mcp")

        self.assertEqual(raised.exception.status_code, 503)
        mocked_text.assert_not_called()

    def test_pypi_recent_does_not_fallback_for_invalid_api_data(self):
        with (
            mock.patch.object(
                stats,
                "request_json",
                return_value={"data": {"last_month": "40,132"}},
            ),
            mock.patch.object(stats, "request_text") as mocked_text,
            self.assertRaisesRegex(stats.StatsError, "invalid count"),
        ):
            stats.JsonClient().pypi_recent("unifi-network-mcp")

        mocked_text.assert_not_called()

    def test_pypi_recent_page_parser_rejects_missing_malformed_or_ambiguous_data(self):
        malformed_pages = {
            "missing": pypi_package_page("unifi-network-mcp", "Downloads last week: 9,608"),
            "bad grouping": pypi_package_page("unifi-network-mcp", "Downloads last month: 40,13"),
            "negative": pypi_package_page("unifi-network-mcp", "Downloads last month: -1"),
            "decimal": pypi_package_page("unifi-network-mcp", "Downloads last month: 401.32"),
            "ambiguous": pypi_package_page(
                "unifi-network-mcp",
                "Downloads last month: 40,132<br>Downloads last month: 40,133",
            ),
        }
        for case, html in malformed_pages.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    stats.StatsError,
                    "PyPI Stats package unifi-network-mcp.*Downloads last month",
                ):
                    stats.parse_pypi_recent_downloads(html, "unifi-network-mcp")

    def test_pypi_recent_page_parser_requires_exact_package_identity(self):
        invalid_pages = {
            "wrong identity": pypi_package_page("another-package", "Downloads last month: 40,132"),
            "missing identity": ("<section><hr><p>Downloads last month: 40,132</p></section>"),
            "duplicate identity": (
                "<section><h1>unifi-network-mcp</h1><h1>unifi-network-mcp</h1>"
                "<hr><p>Downloads last month: 40,132</p></section>"
            ),
        }
        for case, html in invalid_pages.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    stats.StatsError,
                    "PyPI Stats package unifi-network-mcp.*identity",
                ):
                    stats.parse_pypi_recent_downloads(html, "unifi-network-mcp")

    def test_pypi_recent_page_parser_requires_metric_in_package_statistics_region(self):
        invalid_pages = {
            "unrelated prose in region": pypi_package_page(
                "unifi-network-mcp",
                "Marketing copy: Downloads last month: 40,132 users saw this page.",
            ),
            "exact phrase in later paragraph": (
                "<section><h1>unifi-network-mcp</h1><hr><p>Package metadata</p>"
                "<p>Downloads last month: 40,132</p></section>"
            ),
            "script only": pypi_package_page(
                "unifi-network-mcp",
                "<script>Downloads last month: 40,132</script>",
            ),
            "style only": pypi_package_page(
                "unifi-network-mcp",
                "<style>Downloads last month: 40,132</style>",
            ),
        }
        for case, html in invalid_pages.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    stats.StatsError,
                    "PyPI Stats package unifi-network-mcp.*Downloads last month",
                ):
                    stats.parse_pypi_recent_downloads(html, "unifi-network-mcp")

    def test_pypi_recent_page_parser_accepts_normalized_identity_and_associated_count(self):
        html = pypi_package_page(
            "  unifi-network-mcp\n",
            "Package metadata<br><br>Downloads last month:\n40,132",
        )

        self.assertEqual(
            stats.parse_pypi_recent_downloads(html, "unifi-network-mcp"),
            40_132,
        )

    def test_package_download_parser_reads_exact_associated_title(self):
        html = """
        <div>
          <span>Total downloads</span>
          <h3 title="123716">124K</h3>
        </div>
        """

        self.assertEqual(stats.parse_package_downloads(html, "unifi-network-mcp"), 123_716)

    def test_package_download_parser_rejects_missing_or_malformed_count(self):
        malformed_pages = {
            "missing label": '<h3 title="123716">124K</h3>',
            "missing title": "<span>Total downloads</span><h3>124K</h3>",
            "formatted title": ('<span>Total downloads</span><h3 title="123,716">124K</h3>'),
            "unassociated title": ('<span>Total downloads</span><div>other content</div><h3 title="123716">124K</h3>'),
        }
        for case, html in malformed_pages.items():
            with self.subTest(case=case):
                with self.assertRaisesRegex(
                    stats.StatsError,
                    "GitHub package page unifi-network-mcp.*Total downloads",
                ):
                    stats.parse_package_downloads(html, "unifi-network-mcp")

    def test_ghcr_package_totals_fetches_all_five_public_pages_without_auth(self):
        pages = [f'<span>Total downloads</span><h3 title="{index}">{index}</h3>' for index in range(1, 6)]
        expected_names = [name for _, name in stats.PACKAGE_MAP.values()]
        with mock.patch.object(stats, "request_text", side_effect=pages) as mocked_request:
            result = stats.JsonClient().ghcr_package_totals("secret-token")

        self.assertEqual(result, dict(zip(expected_names, range(1, 6), strict=True)))
        self.assertEqual(mocked_request.call_count, 5)
        for call, package_name in zip(mocked_request.call_args_list, expected_names, strict=True):
            request = call.args[0]
            self.assertEqual(
                request.full_url,
                f"{stats.GITHUB_PACKAGE_BASE}{package_name}",
            )
            self.assertIsNone(request.get_header("Authorization"))

    def test_ghcr_package_totals_names_missing_package_page_error(self):
        with mock.patch.object(
            stats,
            "request_text",
            side_effect=stats.StatsError("GitHub package page unifi-network-mcp request failed with HTTP 404"),
        ):
            with self.assertRaisesRegex(stats.StatsError, "GitHub package page unifi-network-mcp.*404"):
                stats.JsonClient().ghcr_package_totals("token")

    def test_stargazers_combines_two_pages_exactly_once(self):
        first_page = [{"starred_at": f"2026-05-{(index % 28) + 1:02d}T00:00:00Z"} for index in range(100)]
        second_page = [{"starred_at": "2026-07-01T00:00:00Z"}]
        with mock.patch.object(stats, "request_json", side_effect=[first_page, second_page]) as mocked_request:
            result = stats.JsonClient().stargazers("token")

        self.assertEqual(result, [item["starred_at"] for item in first_page + second_page])
        self.assertEqual(mocked_request.call_count, 2)
        requested_urls = [call.args[0].full_url for call in mocked_request.call_args_list]
        self.assertIn("page=1", requested_urls[0])
        self.assertIn("page=2", requested_urls[1])

    def test_stargazers_rejects_malformed_timestamp(self):
        payload = [{"starred_at": "not-a-timestamp"}]
        with mock.patch.object(stats, "request_json", return_value=payload):
            with self.assertRaisesRegex(stats.StatsError, "GitHub stargazers.*timestamp"):
                stats.JsonClient().stargazers("token")

    def test_repository_rejects_malformed_stargazer_count(self):
        malformed_values = [None, "509", True, -1]
        for value in malformed_values:
            with self.subTest(value=value):
                with mock.patch.object(
                    stats,
                    "request_json",
                    return_value={"stargazers_count": value},
                ):
                    with self.assertRaisesRegex(
                        stats.StatsError,
                        "GitHub repository.*stargazers_count.*invalid count",
                    ):
                        stats.JsonClient().repository("token")

    def test_repository_rejects_missing_stargazer_count(self):
        with mock.patch.object(stats, "request_json", return_value={}):
            with self.assertRaisesRegex(stats.StatsError, "GitHub repository.*stargazers_count"):
                stats.JsonClient().repository("token")

    def test_merged_pull_requests_combines_two_pages_exactly_once(self):
        first_page = [{"user": {"login": f"user-{index}", "type": "User"}} for index in range(100)]
        second_page = [{"user": {"login": "last-user", "type": "User"}}]
        with mock.patch.object(
            stats,
            "request_json",
            side_effect=[
                {
                    "incomplete_results": False,
                    "total_count": 101,
                    "items": first_page,
                },
                {
                    "incomplete_results": False,
                    "total_count": 101,
                    "items": second_page,
                },
            ],
        ) as mocked_request:
            result = stats.JsonClient().merged_pull_requests("token", datetime(2026, 4, 11, tzinfo=UTC))

        self.assertEqual(result, first_page + second_page)
        self.assertEqual(mocked_request.call_count, 2)

    def test_merged_pull_requests_rejects_incomplete_search_results(self):
        payload = {"incomplete_results": True, "total_count": 1, "items": []}
        with mock.patch.object(stats, "request_json", return_value=payload):
            with self.assertRaisesRegex(stats.StatsError, "GitHub merged pull requests.*incomplete"):
                stats.JsonClient().merged_pull_requests("token", datetime(2026, 4, 11, tzinfo=UTC))

    def test_merged_pull_requests_rejects_unfulfilled_total_count(self):
        first_page = [{"user": {"login": f"user-{index}", "type": "User"}} for index in range(100)]
        responses = [
            {
                "incomplete_results": False,
                "total_count": 101,
                "items": first_page,
            },
            {"incomplete_results": False, "total_count": 101, "items": []},
        ]
        with mock.patch.object(stats, "request_json", side_effect=responses):
            with self.assertRaisesRegex(stats.StatsError, "GitHub merged pull requests.*101.*100"):
                stats.JsonClient().merged_pull_requests("token", datetime(2026, 4, 11, tzinfo=UTC))

    def test_merged_pull_requests_rejects_unpageable_total_count(self):
        payload = {
            "incomplete_results": False,
            "total_count": 1_001,
            "items": [{"user": {"login": f"user-{index}", "type": "User"}} for index in range(100)],
        }
        with mock.patch.object(stats, "request_json", return_value=payload):
            with self.assertRaisesRegex(stats.StatsError, "GitHub merged pull requests.*1,000"):
                stats.JsonClient().merged_pull_requests("token", datetime(2026, 4, 11, tzinfo=UTC))

    def test_merged_pull_requests_rejects_malformed_user(self):
        payload = {
            "incomplete_results": False,
            "total_count": 1,
            "items": [{"user": {"type": "User"}}],
        }
        with mock.patch.object(stats, "request_json", return_value=payload):
            with self.assertRaisesRegex(stats.StatsError, "GitHub merged pull requests.*user"):
                stats.JsonClient().merged_pull_requests("token", datetime(2026, 4, 11, tzinfo=UTC))


class OutputTests(unittest.TestCase):
    def valid_snapshot(self, generated_at: str) -> dict[str, Any]:
        python_packages = {name: 1 for name, _ in stats.PACKAGE_MAP.values()}
        container_packages = {name: 2 for _, name in stats.PACKAGE_MAP.values()}
        period_end = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        period_start = (period_end - timedelta(days=90)).isoformat().replace("+00:00", "Z")
        return {
            "schema_version": 1,
            "generated_at": generated_at,
            "python": {
                "period": "trailing_30_days",
                "total": sum(python_packages.values()),
                "packages": python_packages,
                "source": stats.PYPI_STATS_BASE,
            },
            "containers": {
                "period": "lifetime",
                "total": sum(container_packages.values()),
                "packages": container_packages,
                "source": stats.GITHUB_PACKAGE_BASE,
            },
            "community": {
                "period": "trailing_90_days",
                "period_start": period_start,
                "period_end": generated_at,
                "merged_pull_requests": 3,
                "contributors": 2,
                "source": "https://api.github.com/search/issues",
            },
            "github": {
                "stars": 509,
                "stars_added_90_days": 20,
                "source": "https://api.github.com/repos/sirkirby/unifi-mcp",
            },
            "npm": {
                "worker_downloads_30_days": 834,
                "source": ("https://api.npmjs.org/downloads/point/last-month/unifi-mcp-worker"),
            },
        }

    def test_atomic_write_preserves_previous_file_when_replace_fails(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            previous = b'{"previous": true}\n'
            output.write_bytes(previous)

            with (
                mock.patch.object(stats.os, "replace", side_effect=OSError("disk error")),
                self.assertRaises(OSError),
            ):
                stats.write_snapshot_atomic(output, {"schema_version": 1})

            self.assertEqual(output.read_bytes(), previous)
            self.assertEqual(list(output.parent.glob(f".{output.name}.*.tmp")), [])

    def test_failed_collection_leaves_previous_output_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            previous = b'{"previous": true}\n'
            output.write_bytes(previous)

            with mock.patch.object(stats, "collect_snapshot", side_effect=stats.StatsError("PyPI failed")):
                result = stats.main(["--output", str(output), "--github-token", "token", "--force"])

            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), previous)

    def test_malformed_pypi_fallback_leaves_previous_output_unchanged(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            previous = b'{"previous": true}\n'
            output.write_bytes(previous)
            rate_limit = stats.StatsHTTPError("PyPI Stats package unifi-network-mcp", 429)

            with (
                mock.patch.object(stats, "request_json", side_effect=rate_limit),
                mock.patch.object(
                    stats,
                    "request_text",
                    return_value=pypi_package_page(
                        "unifi-network-mcp",
                        "Downloads last month: unavailable",
                    ),
                ),
            ):
                result = stats.main(["--output", str(output), "--github-token", "token", "--force"])

            self.assertEqual(result, 1)
            self.assertEqual(output.read_bytes(), previous)

    def test_same_day_cache_is_reused_unless_force_is_passed(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            cached = self.valid_snapshot(f"{today}T00:00:00Z")
            output.write_text(json.dumps(cached), encoding="utf-8")
            replacement = self.valid_snapshot(f"{today}T12:00:00Z")

            with mock.patch.object(stats, "collect_snapshot", return_value=replacement) as mocked_collect:
                cached_result = stats.main(["--output", str(output), "--github-token", "token"])
                forced_result = stats.main(["--output", str(output), "--github-token", "token", "--force"])

            self.assertEqual(cached_result, 0)
            self.assertEqual(forced_result, 0)
            mocked_collect.assert_called_once()
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), replacement)

    def test_malformed_same_day_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            malformed = self.valid_snapshot(f"{today}T00:00:00Z")
            del malformed["community"]
            output.write_text(json.dumps(malformed), encoding="utf-8")
            replacement = self.valid_snapshot(f"{today}T12:00:00Z")

            with mock.patch.object(stats, "collect_snapshot", return_value=replacement) as mocked_collect:
                result = stats.main(["--output", str(output), "--github-token", "token"])

            self.assertEqual(result, 0)
            mocked_collect.assert_called_once()
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), replacement)

    def test_old_schema_same_day_cache_is_not_reused(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "project-stats.json"
            today = datetime.now(UTC).strftime("%Y-%m-%d")
            old_schema = self.valid_snapshot(f"{today}T00:00:00Z")
            old_schema["schema_version"] = 0
            output.write_text(json.dumps(old_schema), encoding="utf-8")
            replacement = self.valid_snapshot(f"{today}T12:00:00Z")

            with mock.patch.object(stats, "collect_snapshot", return_value=replacement) as mocked_collect:
                result = stats.main(["--output", str(output), "--github-token", "token"])

            self.assertEqual(result, 0)
            mocked_collect.assert_called_once()

    def test_non_integer_schema_same_day_cache_is_not_reused(self):
        for schema_version in (True, 1.0, "1"):
            with self.subTest(schema_version=schema_version):
                with tempfile.TemporaryDirectory() as directory:
                    output = Path(directory) / "project-stats.json"
                    today = datetime.now(UTC).strftime("%Y-%m-%d")
                    invalid_schema = self.valid_snapshot(f"{today}T00:00:00Z")
                    invalid_schema["schema_version"] = schema_version
                    output.write_text(json.dumps(invalid_schema), encoding="utf-8")
                    replacement = self.valid_snapshot(f"{today}T12:00:00Z")

                    with mock.patch.object(stats, "collect_snapshot", return_value=replacement) as mocked_collect:
                        result = stats.main(["--output", str(output), "--github-token", "token"])

                    self.assertEqual(result, 0)
                    mocked_collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
