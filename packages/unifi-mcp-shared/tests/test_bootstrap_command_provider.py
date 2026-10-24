"""Security and lifecycle contract for the ``_COMMAND`` credential provider.

The helper is a program, so three properties are load-bearing and each has a
test here: it resolves nothing out of the working directory the MCP client
picked, nothing it writes to either stream is ever logged, and its whole process
tree dies when it runs out of time. The prose contract is in
``docs/credential-providers.md``.
"""

from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest
from unifi_mcp_shared import bootstrap

SENTINEL = "SENTINEL-helper-secret-4d91"


@pytest.fixture(autouse=True)
def _isolated(monkeypatch):
    for name in list(os.environ):
        if name.startswith("UNIFI_"):
            monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", None)
    yield


def _resolve(key: str = "password"):
    return bootstrap.resolve_env(key, env_prefix="NETWORK", logger=logging.getLogger("test"))


@pytest.fixture
def helper(tmp_path):
    """Write an executable /bin/sh helper and return its absolute path."""

    def _make(body: str, name: str = "helper.sh") -> Path:
        path = tmp_path / name
        path.write_text(f"#!/bin/sh\n{body}\n", encoding="utf-8")
        path.chmod(0o755)
        return path

    return _make


@contextlib.contextmanager
def _refused(caplog):
    """Assert the block refuses startup with the credential exit code."""
    with caplog.at_level(logging.DEBUG), pytest.raises(SystemExit) as exc:
        yield
    assert exc.value.code == 6


# ---------------------------------------------------------------------------
# P1 — the helper must not resolve anything out of the project directory
# ---------------------------------------------------------------------------


def test_project_directory_module_does_not_shadow_a_module_helper(monkeypatch, tmp_path, caplog):
    """`python -m helper` in an untrusted project must not import that project's helper.py."""
    marker = tmp_path / "SHADOW-RAN"
    (tmp_path / "helper.py").write_text(
        textwrap.dedent(f"""
            import pathlib
            pathlib.Path({str(marker)!r}).write_text("ran")
            print({SENTINEL!r})
        """),
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"{sys.executable} -m helper")

    with _refused(caplog):
        _resolve()

    assert not marker.exists(), "the project's helper.py was imported and executed"
    assert SENTINEL not in caplog.text


def test_project_directory_script_is_not_reachable_by_a_bare_name(monkeypatch, tmp_path, caplog, helper):
    """A bare executable name resolves on PATH, never against the project directory."""
    helper(f"printf '%s' {SENTINEL}", name="unifi-helper-shim")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "unifi-helper-shim")

    with _refused(caplog):
        _resolve()

    assert "PATH" in caplog.text


def test_relative_path_executable_is_refused_by_name(monkeypatch, tmp_path, caplog, helper):
    """`./helper` names the untrusted directory explicitly; refuse rather than guess."""
    helper(f"printf '%s' {SENTINEL}")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "./helper.sh")

    with _refused(caplog):
        _resolve()

    assert "absolute" in caplog.text.lower()


def test_absolute_helper_still_runs_and_its_value_is_used(monkeypatch, helper):
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(helper("printf '%s' from-helper")))
    assert _resolve() == "from-helper"


def test_helper_does_not_run_in_the_project_directory(monkeypatch, tmp_path, helper):
    """The helper's cwd is a neutral directory, not the project the client opened."""
    project = tmp_path / "project"
    project.mkdir()
    path = helper("pwd", name="pwd-helper.sh")
    monkeypatch.chdir(project)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    where = _resolve()

    assert os.path.realpath(where) != os.path.realpath(project)


# ---------------------------------------------------------------------------
# P1 — a failing helper's stderr must not reach the log
# ---------------------------------------------------------------------------


def test_failing_helper_stderr_is_never_logged(monkeypatch, caplog, helper):
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(helper(f"echo '{SENTINEL}' >&2\nexit 3", name="noisy.sh")))

    with _refused(caplog):
        _resolve()

    assert SENTINEL not in caplog.text
    # Fixed operation context stays: the variable, the executable and the status.
    assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
    assert "noisy.sh exited with status 3" in caplog.text


@pytest.mark.parametrize("exit_code", [0, 1])
def test_helper_stdout_is_never_logged(monkeypatch, caplog, helper, exit_code):
    """The credential arrives on stdout; neither a success nor a failure may log it."""
    path = helper(f"printf '%s' {SENTINEL}\nexit {exit_code}")
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    with caplog.at_level(logging.DEBUG):
        if exit_code:
            with pytest.raises(SystemExit) as exc:
                _resolve()
            assert exc.value.code == 6
        else:
            assert _resolve() == SENTINEL

    assert SENTINEL not in caplog.text


# ---------------------------------------------------------------------------
# P2 — the timeout must own the whole process tree
# ---------------------------------------------------------------------------


def test_timeout_terminates_helper_descendants(monkeypatch, tmp_path, caplog, helper):
    """A descendant that outlives the direct child must not survive the timeout."""
    marker = tmp_path / "DESCENDANT-RAN"
    path = helper(f"(sleep 0.8; touch {marker}) &\nsleep 10", name="spawner.sh")
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 0.3)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    with _refused(caplog):
        _resolve()

    # Watch past the moment the descendant would have written its marker.
    deadline = time.monotonic() + 1.8
    while time.monotonic() < deadline:
        assert not marker.exists(), "a descendant of the helper outlived the timeout"
        time.sleep(0.1)


def test_timeout_message_names_the_variable_without_helper_text(monkeypatch, caplog, helper):
    path = helper(f"echo '{SENTINEL}' >&2\nsleep 10", name="slow.sh")
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 0.3)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    with _refused(caplog):
        _resolve()

    assert SENTINEL not in caplog.text
    assert "UNIFI_NETWORK_PASSWORD_COMMAND" in caplog.text
    assert "did not finish" in caplog.text


# ---------------------------------------------------------------------------
# Contract carried over from the file provider
# ---------------------------------------------------------------------------


def test_command_from_dotenv_is_refused_when_a_snapshot_was_taken(monkeypatch, tmp_path, caplog, helper):
    marker = tmp_path / "RAN"
    path = helper(f"touch {marker}\nprintf '%s' {SENTINEL}")
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_NETWORK_HOST"}))
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    with _refused(caplog):
        _resolve()

    assert not marker.exists()
    assert ".env" in caplog.text


def test_helper_does_not_see_dotenv_injected_loader_variables(monkeypatch, helper):
    """A .env arriving after the snapshot must not reach the helper's environment."""
    path = helper('printf "%s" "${EVIL_FROM_DOTENV:-clean}"', name="echo-env.sh")
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset(os.environ) | {"UNIFI_NETWORK_PASSWORD_COMMAND"})
    monkeypatch.setenv("EVIL_FROM_DOTENV", "1")  # arrives after the snapshot
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(path))

    assert _resolve() == "clean"


def test_three_spellings_at_one_level_are_refused(monkeypatch, tmp_path, caplog):
    (tmp_path / "pw").write_text("x")
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD", "plain")
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_FILE", str(tmp_path / "pw"))
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "/bin/true")

    with _refused(caplog):
        _resolve()

    assert "plain" not in caplog.text


# ---------------------------------------------------------------------------
# Output size is bounded while the helper runs, not after it finishes
# ---------------------------------------------------------------------------


def test_a_helper_that_never_stops_writing_is_refused_without_buffering_it(monkeypatch, caplog, helper):
    """The cap holds during the read, so a runaway helper cannot exhaust memory.

    Draining the pipe first and measuring afterwards would buffer for the whole
    timeout: at observed throughput that is gigabytes before the size check runs.
    """
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 5)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"{helper('exec cat /dev/zero')}")

    started = time.monotonic()
    with _refused(caplog):
        _resolve()

    assert "produced more than" in caplog.text
    # Refused on the overrun, not by waiting the deadline out.
    assert time.monotonic() - started < 4


@pytest.mark.parametrize(("length", "accepted"), [(16, True), (17, False)])
def test_the_cap_is_a_boundary_not_an_approximation(monkeypatch, caplog, helper, length, accepted):
    """Exactly the cap resolves; one byte past it refuses."""
    monkeypatch.setattr(bootstrap, "_SECRET_MAX_BYTES", 16)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"{helper(f"printf %{length}s | tr ' ' x")}")

    if accepted:
        assert _resolve() == "x" * length
    else:
        with _refused(caplog):
            _resolve()
        assert "produced more than" in caplog.text


# ---------------------------------------------------------------------------
# Windows is unverified and says so at runtime
# ---------------------------------------------------------------------------


def test_windows_logs_that_the_provider_is_unverified_there(caplog):
    """The doc calls Windows unverified; the running server should say so too.

    The platform is a parameter rather than a monkeypatched ``os.name``:
    rebinding that global also rewires pytest's own path handling, which fails
    the run under ``-v`` before any assertion is reached.
    """
    with caplog.at_level(logging.WARNING):
        bootstrap._warn_unverified_platform("UNIFI_NETWORK_PASSWORD_COMMAND", logging.getLogger("t"), os_name="nt")
    assert "unverified on Windows" in caplog.text

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        bootstrap._warn_unverified_platform("UNIFI_NETWORK_PASSWORD_COMMAND", logging.getLogger("t"), os_name="posix")
    assert caplog.text == ""


def test_the_windows_read_path_is_capped_too(monkeypatch, helper):
    """The cap is a property of the provider, not of one platform's read.

    Draining with communicate() on the Windows branch bounded nothing; a helper
    writing without end reached gigabytes of RSS before the deadline.
    """
    monkeypatch.setattr(bootstrap, "_SECRET_MAX_BYTES", 4096)
    script = helper("exec cat /dev/zero", name="spew.sh")
    proc = subprocess.Popen(
        [str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        bufsize=0,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    try:
        data, reason = bootstrap._read_capped(proc, 5.0, os_name="nt")
    finally:
        bootstrap._terminate_process_tree(proc, "V", "spew.sh", logging.getLogger("t"))

    assert reason == "overrun"
    assert data is not None and len(data) <= bootstrap._SECRET_MAX_BYTES + 1


def test_a_signal_that_cannot_be_delivered_still_refuses(monkeypatch, caplog, helper):
    """EPERM from killpg -- a helper that changed uid -- must not escape as a traceback."""
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 0.3)
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_GRACE_S", 0.3)
    monkeypatch.setattr(os, "killpg", lambda *a: (_ for _ in ()).throw(PermissionError(1, "Operation not permitted")))
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"{helper('sleep 20')}")

    with _refused(caplog):
        _resolve()


def test_a_helper_that_leaves_a_detached_descendant_still_refuses(helper, tmp_path):
    """A descendant outside the helper's session must not hang startup.

    Out of process on purpose: this failure mode was an unbounded block inside
    ``BufferedReader.close()``, which no in-process timeout can interrupt. The
    helper here SUCCEEDS and exits 0 -- only its detached child holds stdout --
    which is the shape docs/credential-providers.md explicitly contemplates.
    """
    # os.setsid() rather than the setsid(1) binary, which util-linux ships and
    # macOS does not: without it the detached child never starts, the helper
    # succeeds, and the test asserts a refusal that cannot happen.
    pidfile = tmp_path / "detached.pid"
    detach = f"import os, time; os.setsid(); open({str(pidfile)!r}, 'w').write(str(os.getpid())); time.sleep(600)"
    script = helper(
        f"'{sys.executable}' -c \"{detach}\" &\nprintf %s the-password",
        name="detached.sh",
    )
    probe = tmp_path / "probe.py"
    probe.write_text(
        textwrap.dedent(f"""
        import logging, os, sys
        from unifi_mcp_shared import bootstrap
        bootstrap._SECRET_COMMAND_TIMEOUT_S = 0.5
        bootstrap._TRUSTED_VARS = None
        os.environ["UNIFI_NETWORK_PASSWORD_COMMAND"] = {str(script)!r}
        try:
            bootstrap.resolve_env("password", env_prefix="NETWORK", logger=logging.getLogger("p"))
        except SystemExit as exc:
            sys.exit(int(exc.code))
        sys.exit(0)
        """),
        encoding="utf-8",
    )
    try:
        result = subprocess.run([sys.executable, str(probe)], capture_output=True, timeout=30, check=False)
        assert result.returncode == 6, f"expected a refusal, got {result.returncode}: {result.stderr[-400:]!r}"
        # The child is started by the helper and may be slow to write its pidfile on a busy machine.
        deadline = time.monotonic() + 10
        while not pidfile.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        assert pidfile.exists(), "the detached descendant never started"
    finally:
        # It left the helper's session deliberately, so nothing in the provider
        # can reach it; this test owns it.
        with contextlib.suppress(Exception):
            os.kill(int(pidfile.read_text()), signal.SIGKILL)


def test_the_helper_is_reaped_rather_than_left_a_zombie(monkeypatch, caplog, helper):
    """SIGKILL delivery is asynchronous, so a zero-length wait never reaps."""
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_TIMEOUT_S", 0.3)
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_GRACE_S", 0.5)
    started: list = []
    real_popen = subprocess.Popen

    class _Spy(real_popen):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            started.append(self)

    monkeypatch.setattr(subprocess, "Popen", _Spy)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", f"{helper(chr(39).join(['trap ', ' TERM']))}\n")

    with _refused(caplog):
        _resolve()

    assert started and started[0].returncode is not None, "the helper was left unreaped"


# ---------------------------------------------------------------------------
# The helper is resolved on the trusted PATH, and only to an absolute path
# ---------------------------------------------------------------------------


def test_a_bare_name_is_not_resolved_on_a_dotenv_supplied_path(monkeypatch, caplog, tmp_path, helper):
    """PATH missing from the snapshot must not fall back to the live environment.

    ``shutil.which(path=None)`` reads ``os.environ['PATH']`` -- the value a
    ``.env`` may have just rewritten -- which would defeat the name filter.
    """
    attacker = tmp_path / "bin"
    attacker.mkdir()
    planted = attacker / "mygpg"
    planted.write_text(f"#!/bin/sh\nprintf %s {SENTINEL}\n", encoding="utf-8")
    planted.chmod(0o755)
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "mygpg")
    monkeypatch.setenv("PATH", str(attacker))
    # The snapshot carries the variable but not PATH.
    monkeypatch.setattr(bootstrap, "_TRUSTED_VARS", frozenset({"UNIFI_NETWORK_PASSWORD_COMMAND"}))

    with _refused(caplog):
        _resolve()

    assert SENTINEL not in caplog.text


def test_a_bare_name_resolving_to_a_relative_path_is_refused(monkeypatch, caplog, tmp_path):
    """An empty PATH element means the working directory, which is not ours to trust."""
    planted = tmp_path / "gpgx"
    planted.write_text(f"#!/bin/sh\nprintf %s {SENTINEL}\n", encoding="utf-8")
    planted.chmod(0o755)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:")
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", "gpgx")

    with _refused(caplog):
        _resolve()

    assert "relative to the working directory" in caplog.text
    assert SENTINEL not in caplog.text


# ---------------------------------------------------------------------------
# The "nothing the helper writes is logged" claim, checked against real fds
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("stream", ["stderr", "stdout"])
def test_nothing_the_helper_writes_reaches_the_servers_own_streams(helper, capfd, monkeypatch, stream):
    """caplog cannot see fd 1 or fd 2, so this one watches the real descriptors.

    A failing helper commonly prints the credential it could not unlock. The
    in-process tests assert on the log records; ``capfd`` captures the file
    descriptors themselves (which a spawned helper would inherit), so it shows
    that the bytes never reach the descriptors an operator actually captures.
    """
    noisy = helper(f"echo {SENTINEL} 1>&{'2' if stream == 'stderr' else '1'}\nexit 3", name="noisy.sh")
    monkeypatch.setenv("UNIFI_NETWORK_PASSWORD_COMMAND", str(noisy))
    root = logging.getLogger()
    handler = logging.StreamHandler(sys.stderr)
    previous_level = root.level
    root.addHandler(handler)
    root.setLevel(logging.DEBUG)
    try:
        with pytest.raises(SystemExit) as exc:
            bootstrap.resolve_env("password", env_prefix="NETWORK", logger=logging.getLogger("p"))
    finally:
        root.removeHandler(handler)
        root.setLevel(previous_level)
    captured = capfd.readouterr()

    assert exc.value.code == 6
    blob = captured.out + captured.err
    assert SENTINEL not in blob, f"helper {stream} reached the server's own streams"
    # The refusal itself must still be there, naming the variable.
    assert "UNIFI_NETWORK_PASSWORD_COMMAND" in blob


def test_the_threaded_reader_accumulates_a_helper_that_writes_in_bursts(helper):
    """Popen uses bufsize=0, so one read() returns only what is already there.

    A helper that writes, pauses, then writes again must yield the whole
    credential. Reading once accepts the first burst as complete, which is a
    silently truncated secret rather than an error.
    """
    script = helper("printf %s first\nsleep 0.4\nprintf %s second\n", name="bursts.sh")
    proc = subprocess.Popen(
        [str(script)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        cwd="/",
        start_new_session=True,
    )
    try:
        # os_name="nt" selects the threaded reader on any platform.
        data, reason = bootstrap._read_capped(proc, 10.0, os_name="nt")
    finally:
        with contextlib.suppress(Exception):
            proc.kill()
            proc.wait(timeout=5)

    assert reason == "eof"
    assert data == b"firstsecond"


def test_a_term_resistant_descendant_is_killed_before_reporting_success(tmp_path, monkeypatch):
    """Reaping the direct helper is not the same as terminating its group.

    The helper's child ignores SIGTERM and stays in the same process group. If
    the direct child's exit is taken as whole-tree termination, that descendant
    survives a reported success.
    """
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_GRACE_S", 0.5)
    marker = tmp_path / "descendant-alive"
    # A shell's `trap "" TERM` does not protect the `sleep` it forks: killpg
    # reaps that and the shell then exits on its own. The descendant has to
    # ignore the signal in its own handler to be genuinely TERM-resistant.
    ignore_term = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(marker)!r}, 'w').close(); time.sleep(600)"
    )
    parent = tmp_path / "parent.sh"
    parent.write_text(
        f"#!/bin/sh\n'{sys.executable}' -c \"{ignore_term}\" &\nsleep 600\n",
        encoding="utf-8",
    )
    parent.chmod(0o755)

    proc = subprocess.Popen(
        [str(parent)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        cwd="/",
        start_new_session=True,
    )
    group = os.getpgid(proc.pid)
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "the TERM-resistant descendant never started"

    try:
        result = bootstrap._terminate_process_tree(
            proc, "UNIFI_NETWORK_PASSWORD_COMMAND", "parent.sh", logging.getLogger("t")
        )
        # Whatever it reports, the group must not still hold members.
        with pytest.raises(ProcessLookupError):
            os.killpg(group, 0)
        assert result is True
    finally:
        with contextlib.suppress(Exception):
            os.killpg(group, 9)
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)


@pytest.mark.parametrize("reap_leader", [False, True])
def test_an_exited_helper_does_not_leave_its_process_group_running(tmp_path, monkeypatch, reap_leader):
    """The group survives its leader, including after that leader is reaped."""
    ready = tmp_path / "descendant-ready"
    descendant = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(ready)!r}, 'w').close(); time.sleep(600)"
    )
    parent = (
        "import subprocess, sys, time\nfrom pathlib import Path\n"
        f"subprocess.Popen([sys.executable, '-c', {descendant!r}])\n"
        f"while not Path({str(ready)!r}).exists(): time.sleep(.01)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", parent],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=0,
        cwd="/",
        start_new_session=True,
    )
    group = proc.pid
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_GRACE_S", 0.2)
    try:
        deadline = time.monotonic() + 10
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert ready.exists(), "the TERM-resistant descendant never started"
        if reap_leader:
            proc.wait(timeout=5)

        # Only the descendant holds stdout after the helper exits. The normal
        # reader reaches its deadline without reaping the helper on this path.
        _, reason = bootstrap._read_capped(proc, 0.3)
        assert reason == "deadline"
        result = bootstrap._terminate_process_tree(proc, "V", "exited-helper", logging.getLogger("t"))

        with pytest.raises(ProcessLookupError):
            os.killpg(group, 0)
        assert result is True
        assert proc.returncode == 0
    finally:
        with contextlib.suppress(ProcessLookupError):
            os.killpg(group, signal.SIGKILL)
        proc.wait(timeout=5)
        if proc.stdout is not None:
            proc.stdout.close()


def test_an_unsignalable_survivor_is_not_reported_as_a_terminated_tree(tmp_path, monkeypatch):
    """EPERM on the escalation must not inherit the direct child's exit.

    A descendant that changed uid leaves a group we may no longer signal. The
    child being reaped says nothing about it, and reporting a terminated tree
    there is the same mistake as reporting one from the child's exit.
    """
    monkeypatch.setattr(bootstrap, "_SECRET_COMMAND_GRACE_S", 0.3)
    marker = tmp_path / "survivor-ready"
    ignore_term = (
        "import signal, time; signal.signal(signal.SIGTERM, signal.SIG_IGN); "
        f"open({str(marker)!r}, 'w').close(); time.sleep(600)"
    )
    parent = tmp_path / "parent.sh"
    parent.write_text(
        f"#!/bin/sh\n'{sys.executable}' -c \"{ignore_term}\" &\nsleep 600\n",
        encoding="utf-8",
    )
    parent.chmod(0o755)

    proc = subprocess.Popen(
        [str(parent)],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd="/",
        start_new_session=True,
    )
    group = os.getpgid(proc.pid)
    # The handler must be installed before the first signal, or the descendant
    # dies to SIGTERM and there is no survivor to detect.
    deadline = time.monotonic() + 10
    while not marker.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert marker.exists(), "the TERM-ignoring descendant never started"
    real_killpg = os.killpg
    calls: list[int] = []

    def _killpg(pgid, sig):
        calls.append(sig)
        if sig == signal.SIGKILL:  # the uid-changed survivor we may not signal
            raise PermissionError(1, "Operation not permitted")
        return real_killpg(pgid, sig)

    monkeypatch.setattr(os, "killpg", _killpg)
    try:
        result = bootstrap._terminate_process_tree(
            proc, "UNIFI_NETWORK_PASSWORD_COMMAND", "parent.sh", logging.getLogger("t")
        )
        assert signal.SIGKILL in calls, "the escalation never ran"
        assert result is False, "a survivor we cannot signal was reported as a terminated tree"
    finally:
        monkeypatch.setattr(os, "killpg", real_killpg)
        with contextlib.suppress(Exception):
            real_killpg(group, signal.SIGKILL)
        with contextlib.suppress(Exception):
            proc.wait(timeout=5)
