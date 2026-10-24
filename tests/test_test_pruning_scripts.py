"""The test-pruning skill's gates must flag weakened tests and fail closed."""

from __future__ import annotations

import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / ".agents" / "skills" / "test-pruning" / "scripts"


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True).stdout.strip()


def _commit(repo: Path, files: dict[str, str]) -> str:
    for name, body in files.items():
        (repo / name).write_text(textwrap.dedent(body))
    _git(repo, "add", "-A")
    _git(
        repo,
        "-c",
        "user.name=t",
        "-c",
        "user.email=t@example.invalid",
        "-c",
        "commit.gpgsign=false",
        "commit",
        "-qm",
        "c",
    )
    return _git(repo, "rev-parse", "HEAD")


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-q")
    return tmp_path


def _scan(repo: Path, base: str, head: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPTS / "weakscan.py"), str(repo), base, head], capture_output=True, text=True
    )


BASE_TEST = """
    def test_convert():
        assert convert({"a": 1}) == {"a": 1}
"""


def test_scan_flags_a_local_input_used_as_the_expected_value(repo: Path) -> None:
    base = _commit(repo, {"test_x.py": BASE_TEST})
    head = _commit(
        repo,
        {
            "test_x.py": """
        def test_convert():
            payload = {"a": 1}
            result = convert(payload)
            assert result == payload
    """
        },
    )

    out = _scan(repo, base, head)

    assert out.returncode == 0, out.stderr
    assert "aliased-expected" in out.stdout


def test_scan_accepts_a_deep_copied_expected_value(repo: Path) -> None:
    base = _commit(repo, {"test_x.py": BASE_TEST})
    head = _commit(
        repo,
        {
            "test_x.py": """
        import copy

        def test_convert():
            payload = {"a": 1}
            expected = copy.deepcopy(payload)
            result = convert(payload)
            assert result == expected
    """
        },
    )

    out = _scan(repo, base, head)

    assert out.returncode == 0, out.stderr
    assert "aliased-expected" not in out.stdout


@pytest.mark.parametrize(
    ("guard", "flagged"),
    [("", True), ("    assert len(result['rows']) == 1\n", False)],
    ids=["unguarded", "length-checked"],
)
def test_scan_flags_a_loop_over_results_only_without_a_length_check(repo: Path, guard: str, flagged: bool) -> None:
    base = _commit(repo, {"test_x.py": BASE_TEST})
    head = _commit(
        repo,
        {
            "test_x.py": (
                "def test_rows():\n"
                "    result = list_rows()\n"
                f"{guard}"
                "    for row in result['rows']:\n"
                "        assert row['id']\n"
            )
        },
    )

    out = _scan(repo, base, head)

    assert out.returncode == 0, out.stderr
    assert ("loop-without-length" in out.stdout) is flagged


def test_scan_fails_on_an_unknown_ref(repo: Path) -> None:
    base = _commit(repo, {"test_x.py": BASE_TEST})

    out = _scan(repo, base, "no-such-branch")

    assert out.returncode == 2
    assert "0 finding" not in out.stdout


GREET = """
    def greet(name):
        return "hi " + name
"""
STRONG = """
    from greet import greet

    def test_greet():
        assert greet("a") == "hi a"
"""


def _mutdiff(repo: Path, base: str, head: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "mutdiff.py"),
            str(repo),
            "greet.py",
            "greet",
            "test_greet.py",
            base,
            head,
            sys.executable,
            "-m",
        ],
        capture_output=True,
        text=True,
        timeout=300,
    )


def test_mutdiff_reports_a_check_the_changed_tests_lost(repo: Path) -> None:
    base = _commit(repo, {"greet.py": GREET, "test_greet.py": STRONG})
    head = _commit(
        repo,
        {
            "test_greet.py": """
        from greet import greet

        def test_greet():
            assert isinstance(greet("a"), str)
    """
        },
    )

    out = _mutdiff(repo, base, head)

    assert out.returncode == 1, out.stdout + out.stderr
    assert "LOST change string" in out.stdout
    assert (repo / "test_greet.py").read_text() == textwrap.dedent("""
        from greet import greet

        def test_greet():
            assert isinstance(greet("a"), str)
    """)


def test_mutdiff_refuses_a_changed_file_with_no_tests(repo: Path) -> None:
    base = _commit(repo, {"greet.py": GREET, "test_greet.py": STRONG})
    head = _commit(repo, {"test_greet.py": "from greet import greet\n"})

    out = _mutdiff(repo, base, head)

    assert out.returncode == 2, out.stdout + out.stderr
    assert "LOST" not in out.stdout
