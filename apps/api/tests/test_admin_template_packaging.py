"""Admin templates must survive repository builds and source distribution installs."""

from __future__ import annotations

import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
TEMPLATE_ROOT = REPO_ROOT / "apps/api/src/unifi_api/templates"


def test_admin_templates_survive_wheel_and_sdist_builds(tmp_path: Path) -> None:
    # Build in the repository: copying the app elsewhere hides VCS-ignore bugs.
    direct = tmp_path / "direct"
    subprocess.run(
        ["uv", "build", "--package", "unifi-api-server", "--wheel", "--sdist", "--out-dir", str(direct)],
        cwd=REPO_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    expected = {
        f"unifi_api/templates/{path.relative_to(TEMPLATE_ROOT).as_posix()}": path.read_bytes()
        for path in TEMPLATE_ROOT.rglob("*.html")
    }
    sdist = next(direct.glob("unifi_api_server-*.tar.gz"))
    with tarfile.open(sdist) as archive:
        names = archive.getnames()
        prefix = names[0].split("/")[0]
        for name, content in expected.items():
            member = f"{prefix}/src/{name}"
            assert names.count(member) == 1, member
            packaged = archive.extractfile(member)
            assert packaged is not None
            assert packaged.read() == content, member

    rebuilt = tmp_path / "rebuilt"
    subprocess.run(
        ["uv", "build", str(sdist), "--wheel", "--out-dir", str(rebuilt)],
        cwd=tmp_path,
        check=True,
        capture_output=True,
        text=True,
    )
    for directory in (direct, rebuilt):
        wheel = next(directory.glob("unifi_api_server-*.whl"))
        unpacked = directory / "unpacked"
        with zipfile.ZipFile(wheel) as archive:
            names = archive.namelist()
            for name, content in expected.items():
                assert names.count(name) == 1, name
                assert archive.read(name) == content, name
            archive.extractall(unpacked)

        # Load the wheel's production renderer, never the editable source tree.
        probe = """
import sys
from pathlib import Path
from starlette.requests import Request

sys.path.insert(0, sys.argv[1])
from unifi_api.routes.admin import _common
assert Path(_common.__file__).is_relative_to(Path(sys.argv[1]))
request = Request({"type": "http", "method": "GET", "path": "/admin/logs", "headers": []})
page = _common.render(request, "logs/list.html")
assert b"Application logs" in page.body and b"logs-filters" in page.body
assert page.headers["cache-control"] == "no-store"
rows = _common.render(request, "logs/_rows.html", {
    "rows": [{"ts": "2026-01-01", "level": "ERROR", "logger": "probe", "event": "<packaged>"}],
    "next_offset": None,
})
assert b"&lt;packaged&gt;" in rows.body
assert b"<packaged>" not in rows.body
"""
        subprocess.run(
            [sys.executable, "-I", "-c", probe, str(unpacked)],
            cwd=tmp_path,
            check=True,
            capture_output=True,
            text=True,
        )
