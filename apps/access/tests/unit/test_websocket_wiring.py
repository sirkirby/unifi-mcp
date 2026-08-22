"""Guard the call site: `main_async` must start the event listener.

`EventManager.start_listening` existed, was unit-tested, and was never called
by the application — `main_async` carried a TODO and a log line claiming the
feature was unimplemented, where the Protect server calls it. The manager tests
passed because they invoked the manager directly, so nothing caught that the
buffer could not fill in production.

This is a call-site guard only; it asserts the wiring exists, not that the
listener works. That behaviour is covered against the real `WebsocketMessage`
contract in `unifi_core.tests.access.managers.test_event_manager_websocket`.
"""

import inspect

from unifi_access_mcp import main as access_main


def test_main_starts_the_event_listener() -> None:
    src = inspect.getsource(access_main.main_async)
    assert "event_manager.start_listening()" in src, "the websocket listener is still never started"
