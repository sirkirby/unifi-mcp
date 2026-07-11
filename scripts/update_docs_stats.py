#!/usr/bin/env python3
"""Collect sourced project statistics for the documentation site."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Mapping, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

PACKAGE_MAP = {
    "network": ("unifi-network-mcp", "unifi-network-mcp"),
    "protect": ("unifi-protect-mcp", "unifi-protect-mcp"),
    "access": ("unifi-access-mcp", "unifi-access-mcp"),
    "api": ("unifi-api-server", "unifi-api-server"),
    "relay": ("unifi-mcp-relay", "unifi-mcp-relay"),
}

USER_AGENT = "unifi-mcp-docs-stats/1"
RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
GITHUB_PACKAGE_BASE = "https://github.com/sirkirby/unifi-mcp/pkgs/container/"
PYPI_STATS_BASE = "https://pypistats.org/"
PYPI_STATS_API_BASE = f"{PYPI_STATS_BASE}api/packages/"
PYPI_STATS_PACKAGE_BASE = f"{PYPI_STATS_BASE}packages/"
SNAPSHOT_KEYS = {
    "schema_version",
    "generated_at",
    "python",
    "containers",
    "community",
    "github",
    "npm",
}


class StatsError(RuntimeError):
    """Raised when a statistics source cannot produce a complete result."""


class StatsHTTPError(StatsError):
    """Raised when a statistics source returns a terminal HTTP response."""

    def __init__(self, source: str, status_code: int) -> None:
        self.source = source
        self.status_code = status_code
        super().__init__(f"{source} request failed with HTTP {status_code}")


def _request_bytes(
    request: Request,
    *,
    source: str,
    attempts: int = 3,
    timeout: float = 30.0,
) -> bytes:
    for attempt in range(attempts):
        try:
            with urlopen(request, timeout=timeout) as response:
                return response.read()
        except HTTPError as exc:
            is_retryable = exc.code in RETRYABLE_STATUS_CODES
            if not is_retryable or attempt == attempts - 1:
                raise StatsHTTPError(source, exc.code) from exc
            retry_after = exc.headers.get("Retry-After") if exc.headers is not None else None
            if retry_after is not None and retry_after.isdigit():
                delay = int(retry_after)
            else:
                delay = min(2**attempt, 8)
            time.sleep(delay)
        except (URLError, TimeoutError) as exc:
            raise StatsError(f"{source} request failed: {exc}") from exc

    raise StatsError(f"{source} request failed after {attempts} attempts")


def request_json(
    request: Request,
    *,
    source: str,
    attempts: int = 3,
    timeout: float = 30.0,
) -> Any:
    """Make an HTTP request and return decoded JSON with bounded retries."""
    try:
        return json.loads(_request_bytes(request, source=source, attempts=attempts, timeout=timeout).decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StatsError(f"{source} returned invalid UTF-8 JSON") from exc


def request_text(
    request: Request,
    *,
    source: str,
    attempts: int = 3,
    timeout: float = 30.0,
) -> str:
    """Make an HTTP request and return decoded UTF-8 text with bounded retries."""
    try:
        return _request_bytes(request, source=source, attempts=attempts, timeout=timeout).decode("utf-8")
    except UnicodeDecodeError as exc:
        raise StatsError(f"{source} returned invalid UTF-8 HTML") from exc


def _request(
    url: str,
    *,
    token: str | None = None,
    accept: str = "application/vnd.github+json",
    data: bytes | None = None,
) -> Request:
    headers = {"Accept": accept, "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if data is not None:
        headers["Content-Type"] = "application/json"
    return Request(url, headers=headers, data=data)


class _PackageDownloadsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._label_parts: list[str] | None = None
        self._awaiting_count = False
        self.candidates: list[str | None] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "span":
            self._label_parts = []
            return
        if not self._awaiting_count:
            return
        if tag == "h3":
            self.candidates.append(dict(attrs).get("title"))
            self._awaiting_count = False
        elif tag in {"article", "div", "h1", "h2", "h4", "p", "section", "span"}:
            self._awaiting_count = False

    def handle_data(self, data: str) -> None:
        if self._label_parts is not None:
            self._label_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "span" or self._label_parts is None:
            return
        label = " ".join("".join(self._label_parts).split())
        self._label_parts = None
        self._awaiting_count = label == "Total downloads"


def parse_package_downloads(html: str, package_name: str) -> int:
    parser = _PackageDownloadsParser()
    parser.feed(html)
    if len(parser.candidates) != 1:
        raise StatsError(f"GitHub package page {package_name} is missing an associated Total downloads count")
    title = parser.candidates[0]
    if title is None or not title.isascii() or not title.isdigit():
        raise StatsError(f"GitHub package page {package_name} has a malformed Total downloads count")
    return _require_count(int(title), f"GitHub package page {package_name}")


class _PyPIRecentDownloadsParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.identities: list[str] = []
        self.candidates: list[str] = []
        self._section_depth = 0
        self._ignored_depth = 0
        self._heading_parts: list[str] | None = None
        self._awaiting_rule = False
        self._awaiting_statistics = False
        self._statistics_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style"}:
            self._ignored_depth += 1
            return
        if self._ignored_depth:
            return
        if tag == "section":
            self._section_depth += 1
            return
        if not self._section_depth:
            return
        if tag == "h1":
            self._heading_parts = []
            return
        if tag == "hr":
            self._awaiting_statistics = self._awaiting_rule
            self._awaiting_rule = False
            return
        if tag == "p" and self._awaiting_statistics:
            self._statistics_parts = []
            self._awaiting_statistics = False
            return
        if tag == "br" and self._statistics_parts is not None:
            self._finish_statistics_segment()
            return
        if self._awaiting_rule:
            self._awaiting_rule = False
        if self._awaiting_statistics:
            self._awaiting_statistics = False

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style"}:
            if self._ignored_depth:
                self._ignored_depth -= 1
            return
        if self._ignored_depth:
            return
        if tag == "h1" and self._heading_parts is not None:
            self.identities.append(" ".join("".join(self._heading_parts).split()))
            self._heading_parts = None
            self._awaiting_rule = True
            return
        if tag == "p" and self._statistics_parts is not None:
            self._finish_statistics_segment()
            self._statistics_parts = None
            return
        if tag == "section" and self._section_depth:
            self._section_depth -= 1
            self._awaiting_rule = False
            self._awaiting_statistics = False

    def handle_data(self, data: str) -> None:
        if self._ignored_depth:
            return
        if self._heading_parts is not None:
            self._heading_parts.append(data)
        if self._statistics_parts is not None:
            self._statistics_parts.append(data)

    def _finish_statistics_segment(self) -> None:
        if self._statistics_parts is None:
            return
        segment = " ".join("".join(self._statistics_parts).split())
        self._statistics_parts = []
        label = "Downloads last month:"
        if segment.startswith(label):
            self.candidates.append(segment.removeprefix(label).strip())


def _parse_displayed_count(value: str, source: str) -> int:
    if not value.isascii():
        raise StatsError(f"{source} has a malformed count")
    groups = value.split(",")
    if len(groups) == 1:
        valid = bool(groups[0]) and groups[0].isdigit()
    else:
        valid = (
            1 <= len(groups[0]) <= 3
            and groups[0].isdigit()
            and all(len(group) == 3 and group.isdigit() for group in groups[1:])
        )
    if not valid:
        raise StatsError(f"{source} has a malformed count")
    return _require_count(int("".join(groups)), source)


def parse_pypi_recent_downloads(html: str, package_name: str) -> int:
    parser = _PyPIRecentDownloadsParser()
    parser.feed(html)
    parser.close()
    expected_identity = " ".join(package_name.split())
    if parser.identities != [expected_identity]:
        raise StatsError(f"PyPI Stats package {package_name} does not have exactly one matching package identity")
    if len(parser.candidates) != 1:
        raise StatsError(f"PyPI Stats package {package_name} is missing an unambiguous Downloads last month count")
    return _parse_displayed_count(
        parser.candidates[0],
        f"PyPI Stats package {package_name} Downloads last month",
    )


class JsonClient:
    """Small source-specific client for public project statistics."""

    def pypi_recent(self, name: str) -> int:
        encoded_name = quote(name, safe="")
        source = f"PyPI Stats package {name}"
        try:
            payload = request_json(
                _request(f"{PYPI_STATS_API_BASE}{encoded_name}/recent"),
                source=source,
            )
        except StatsHTTPError as exc:
            if exc.status_code != 429:
                raise
            html = request_text(
                _request(
                    f"{PYPI_STATS_PACKAGE_BASE}{encoded_name}",
                    accept="text/html",
                ),
                source=f"PyPI Stats package page {name}",
            )
            return parse_pypi_recent_downloads(html, name)
        try:
            value = payload["data"]["last_month"]
        except (KeyError, TypeError) as exc:
            raise StatsError(f"PyPI Stats package {name} returned invalid data") from exc
        return _require_count(value, f"PyPI Stats package {name}")

    def ghcr_package_totals(self, token: str) -> dict[str, int]:
        del token  # Public package pages must not receive GitHub authorization.
        totals: dict[str, int] = {}
        for _, package_name in PACKAGE_MAP.values():
            source = f"GitHub package page {package_name}"
            html = request_text(
                _request(
                    f"{GITHUB_PACKAGE_BASE}{quote(package_name, safe='')}",
                    accept="text/html",
                ),
                source=source,
            )
            totals[package_name] = parse_package_downloads(html, package_name)
        return totals

    def repository(self, token: str) -> dict[str, Any]:
        payload = request_json(
            _request("https://api.github.com/repos/sirkirby/unifi-mcp", token=token),
            source="GitHub repository",
        )
        try:
            stars = payload["stargazers_count"]
        except (KeyError, TypeError) as exc:
            raise StatsError("GitHub repository response is missing stargazers_count") from exc
        return {"stargazers_count": _require_count(stars, "GitHub repository stargazers_count")}

    def stargazers(self, token: str) -> list[str]:
        starred_at: list[str] = []
        for page in range(1, 101):
            query = urlencode({"per_page": 100, "page": page})
            payload = request_json(
                _request(
                    f"https://api.github.com/repos/sirkirby/unifi-mcp/stargazers?{query}",
                    token=token,
                    accept="application/vnd.github.star+json",
                ),
                source="GitHub stargazers",
            )
            if not isinstance(payload, list):
                raise StatsError("GitHub stargazers returned invalid data")
            try:
                page_timestamps = [item["starred_at"] for item in payload]
            except (KeyError, TypeError) as exc:
                raise StatsError("GitHub stargazers returned invalid data") from exc
            for timestamp in page_timestamps:
                _parse_timestamp(timestamp, "GitHub stargazers starred_at timestamp")
            starred_at.extend(page_timestamps)
            if len(payload) < 100:
                break
        return starred_at

    def merged_pull_requests(self, token: str, cutoff: datetime) -> list[dict[str, Any]]:
        pull_requests: list[dict[str, Any]] = []
        expected_total: int | None = None
        search = f"repo:sirkirby/unifi-mcp is:pr is:merged merged:>={_iso_z(cutoff)}"
        for page in range(1, 11):
            query = urlencode({"q": search, "per_page": 100, "page": page, "sort": "created"})
            payload = request_json(
                _request(f"https://api.github.com/search/issues?{query}", token=token),
                source="GitHub merged pull requests",
            )
            try:
                incomplete_results = payload["incomplete_results"]
                total_count = _require_count(payload["total_count"], "GitHub merged pull requests total_count")
                items = payload["items"]
            except (KeyError, TypeError) as exc:
                raise StatsError("GitHub merged pull requests returned invalid data") from exc
            if incomplete_results is not False:
                raise StatsError("GitHub merged pull requests search returned incomplete results")
            if total_count > 1_000:
                raise StatsError("GitHub merged pull requests search exceeds the 1,000-result pagination limit")
            if expected_total is None:
                expected_total = total_count
            elif total_count != expected_total:
                raise StatsError("GitHub merged pull requests total_count changed during pagination")
            if not isinstance(items, list):
                raise StatsError("GitHub merged pull requests returned invalid data")
            if len(items) > 100 or len(pull_requests) + len(items) > expected_total:
                raise StatsError("GitHub merged pull requests returned an invalid page size")
            for item in items:
                _pull_request_user(item)
            pull_requests.extend(items)
            if len(pull_requests) == expected_total:
                return pull_requests
            if len(items) < 100:
                raise StatsError(
                    "GitHub merged pull requests reports total_count "
                    f"{expected_total} but only {len(pull_requests)} items were available"
                )
        raise StatsError("GitHub merged pull requests pagination ended before all results were fetched")

    def npm_downloads(self) -> int:
        url = "https://api.npmjs.org/downloads/point/last-month/unifi-mcp-worker"
        payload = request_json(_request(url), source="npm downloads")
        try:
            value = payload["downloads"]
        except (KeyError, TypeError) as exc:
            raise StatsError("npm downloads returned invalid data") from exc
        return _require_count(value, "npm downloads")


def _require_count(value: Any, source: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise StatsError(f"{source} returned an invalid count")
    return value


def _pull_request_user(item: Any) -> tuple[str, str]:
    try:
        user = item["user"]
        login = user["login"]
        user_type = user["type"]
    except (KeyError, TypeError) as exc:
        raise StatsError("GitHub merged pull requests returned a malformed user") from exc
    if not isinstance(login, str) or not login or not isinstance(user_type, str) or not user_type:
        raise StatsError("GitHub merged pull requests returned a malformed user")
    return login, user_type


def _iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_timestamp(value: Any, source: str) -> datetime:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise StatsError(f"{source} must be a UTC timestamp ending in Z")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise StatsError(f"{source} contains an invalid timestamp") from exc
    if parsed.utcoffset() != timedelta(0):
        raise StatsError(f"{source} must be a UTC timestamp")
    return parsed


def _require_section(snapshot: Mapping[str, Any], name: str, keys: set[str]) -> Mapping[str, Any]:
    section = snapshot.get(name)
    if not isinstance(section, dict) or set(section) != keys:
        raise StatsError(f"Snapshot {name} section does not match schema version 1")
    return section


def _require_source(section: Mapping[str, Any], name: str, expected: str) -> None:
    if section["source"] != expected:
        raise StatsError(f"Snapshot {name} source does not match schema version 1")


def validate_snapshot(snapshot: Any) -> None:
    """Validate the complete committed snapshot contract."""
    if not isinstance(snapshot, dict) or set(snapshot) != SNAPSHOT_KEYS:
        raise StatsError("Snapshot top-level keys do not match schema version 1")
    if type(snapshot["schema_version"]) is not int or snapshot["schema_version"] != 1:
        raise StatsError("Snapshot schema_version must be 1")
    generated_at = _parse_timestamp(snapshot["generated_at"], "Snapshot generated_at")

    python = _require_section(snapshot, "python", {"period", "total", "packages", "source"})
    containers = _require_section(snapshot, "containers", {"period", "total", "packages", "source"})
    expected_python = {name for name, _ in PACKAGE_MAP.values()}
    expected_containers = {name for _, name in PACKAGE_MAP.values()}
    for section, name, period, package_names, source in (
        (
            python,
            "python",
            "trailing_30_days",
            expected_python,
            PYPI_STATS_BASE,
        ),
        (
            containers,
            "containers",
            "lifetime",
            expected_containers,
            GITHUB_PACKAGE_BASE,
        ),
    ):
        if section["period"] != period:
            raise StatsError(f"Snapshot {name} period does not match schema version 1")
        packages = section["packages"]
        if not isinstance(packages, dict) or set(packages) != package_names:
            raise StatsError(f"Snapshot {name} packages do not match the required package map")
        package_total = sum(
            _require_count(value, f"Snapshot {name} package {package}") for package, value in packages.items()
        )
        if _require_count(section["total"], f"Snapshot {name} total") != package_total:
            raise StatsError(f"Snapshot {name} total does not match its packages")
        _require_source(section, name, source)

    community = _require_section(
        snapshot,
        "community",
        {
            "period",
            "period_start",
            "period_end",
            "merged_pull_requests",
            "contributors",
            "source",
        },
    )
    if community["period"] != "trailing_90_days":
        raise StatsError("Snapshot community period does not match schema version 1")
    period_start = _parse_timestamp(community["period_start"], "Snapshot community period_start")
    period_end = _parse_timestamp(community["period_end"], "Snapshot community period_end")
    if period_end != generated_at or period_start != period_end - timedelta(days=90):
        raise StatsError("Snapshot community period bounds do not match generated_at")
    _require_count(community["merged_pull_requests"], "Snapshot community merged pull requests")
    _require_count(community["contributors"], "Snapshot community contributors")
    _require_source(community, "community", "https://api.github.com/search/issues")

    github = _require_section(snapshot, "github", {"stars", "stars_added_90_days", "source"})
    _require_count(github["stars"], "Snapshot GitHub stars")
    _require_count(github["stars_added_90_days"], "Snapshot GitHub stars added")
    _require_source(github, "github", "https://api.github.com/repos/sirkirby/unifi-mcp")

    npm = _require_section(snapshot, "npm", {"worker_downloads_30_days", "source"})
    _require_count(npm["worker_downloads_30_days"], "Snapshot npm downloads")
    _require_source(
        npm,
        "npm",
        "https://api.npmjs.org/downloads/point/last-month/unifi-mcp-worker",
    )


def collect_snapshot(client: JsonClient, token: str, now: datetime) -> dict[str, Any]:
    cutoff = now - timedelta(days=90)
    python_packages: dict[str, int] = {}
    for pypi_name, _ in PACKAGE_MAP.values():
        try:
            python_packages[pypi_name] = _require_count(client.pypi_recent(pypi_name), f"PyPI package {pypi_name}")
        except KeyError as exc:
            raise StatsError(f"PyPI package {pypi_name} is missing") from exc
    ghcr_totals = client.ghcr_package_totals(token)
    container_packages: dict[str, int] = {}
    for _, ghcr_name in PACKAGE_MAP.values():
        try:
            container_packages[ghcr_name] = _require_count(ghcr_totals[ghcr_name], f"GHCR package {ghcr_name}")
        except KeyError as exc:
            raise StatsError(f"GHCR package {ghcr_name} is missing") from exc
    eligible_pull_requests: list[dict[str, Any]] = []
    contributors: set[str] = set()
    for item in client.merged_pull_requests(token, cutoff):
        login, user_type = _pull_request_user(item)
        if user_type != "Bot" and login.casefold() != "sirkirby":
            eligible_pull_requests.append(item)
            contributors.add(login.casefold())
    starred_at = client.stargazers(token)
    repository = client.repository(token)
    try:
        repository_stars = repository["stargazers_count"]
    except (KeyError, TypeError) as exc:
        raise StatsError("GitHub repository response is missing stargazers_count") from exc
    repository_stars = _require_count(repository_stars, "GitHub repository stargazers_count")
    parsed_stargazers = [_parse_timestamp(value, "GitHub stargazers starred_at timestamp") for value in starred_at]

    return {
        "schema_version": 1,
        "generated_at": _iso_z(now),
        "python": {
            "period": "trailing_30_days",
            "total": sum(python_packages.values()),
            "packages": dict(sorted(python_packages.items())),
            "source": PYPI_STATS_BASE,
        },
        "containers": {
            "period": "lifetime",
            "total": sum(container_packages.values()),
            "packages": dict(sorted(container_packages.items())),
            "source": GITHUB_PACKAGE_BASE,
        },
        "community": {
            "period": "trailing_90_days",
            "period_start": _iso_z(cutoff),
            "period_end": _iso_z(now),
            "merged_pull_requests": len(eligible_pull_requests),
            "contributors": len(contributors),
            "source": "https://api.github.com/search/issues",
        },
        "github": {
            "stars": repository_stars,
            "stars_added_90_days": sum(value >= cutoff for value in parsed_stargazers),
            "source": "https://api.github.com/repos/sirkirby/unifi-mcp",
        },
        "npm": {
            "worker_downloads_30_days": client.npm_downloads(),
            "source": ("https://api.npmjs.org/downloads/point/last-month/unifi-mcp-worker"),
        },
    }


def write_snapshot_atomic(path: Path, snapshot: Mapping[str, Any]) -> None:
    """Write a deterministic snapshot without exposing a partial target file."""
    path.parent.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    temporary_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary:
            temporary_path = Path(temporary.name)
            temporary.write(serialized)
            temporary.flush()
            os.fsync(temporary.fileno())
        os.replace(temporary_path, path)
    except BaseException:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)
        raise


def _same_day_cache(path: Path, now: datetime) -> bool:
    try:
        cached = json.loads(path.read_text(encoding="utf-8"))
        validate_snapshot(cached)
        generated_at = _parse_timestamp(cached["generated_at"], "Snapshot generated_at")
    except (OSError, StatsError, json.JSONDecodeError):
        return False
    return generated_at.astimezone(UTC).date() == now.astimezone(UTC).date()


def _github_token(explicit_token: str | None) -> str:
    token = explicit_token or os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if token:
        return token
    try:
        result = subprocess.run(
            ["gh", "auth", "token"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (FileNotFoundError, subprocess.CalledProcessError) as exc:
        raise StatsError("GitHub authentication is required. Pass --github-token or authenticate gh.") from exc
    token = result.stdout.strip()
    if not token:
        raise StatsError("GitHub authentication is required. Pass --github-token or authenticate gh.")
    return token


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("docs/data/project-stats.json"),
        help="Snapshot output path",
    )
    parser.add_argument("--github-token", help="GitHub token for API requests")
    parser.add_argument("--force", action="store_true", help="Ignore a same-day local snapshot")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    now = datetime.now(UTC)
    if not args.force and _same_day_cache(args.output, now):
        print(f"Reusing same-day project statistics snapshot: {args.output}")
        return 0

    try:
        token = _github_token(args.github_token)
        snapshot = collect_snapshot(JsonClient(), token, now)
        validate_snapshot(snapshot)
        write_snapshot_atomic(args.output, snapshot)
    except StatsError as exc:
        print(f"Unable to update project statistics: {exc}", file=sys.stderr)
        return 1

    print(
        "Updated project statistics: "
        f"{len(snapshot['python']['packages'])} PyPI packages "
        f"({snapshot['python']['period']}), "
        f"{len(snapshot['containers']['packages'])} GHCR packages "
        f"({snapshot['containers']['period']}) -> {args.output}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
