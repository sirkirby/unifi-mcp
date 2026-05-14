"""SubscriberPool unit tests."""

from unittest.mock import MagicMock

import pytest
from unifi_api.services.streams import StreamSubscriber, SubscriberPool


@pytest.mark.asyncio
async def test_attach_registers_callback_with_manager() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    unsub = MagicMock()
    mgr.add_subscriber.return_value = unsub
    sub = await pool.attach("ctrl1", "network", mgr)
    assert isinstance(sub, StreamSubscriber)
    mgr.add_subscriber.assert_called_once()
    # second attach reuses the same manager registration (one callback, fan-out is internal)
    await pool.attach("ctrl1", "network", mgr)
    assert mgr.add_subscriber.call_count == 1


@pytest.mark.asyncio
async def test_broadcast_pushes_to_all_subscribers() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    captured_cb = {}

    def fake_add_sub(cb):
        captured_cb["cb"] = cb
        return MagicMock()

    mgr.add_subscriber.side_effect = fake_add_sub
    sub_a = await pool.attach("ctrl1", "network", mgr)
    sub_b = await pool.attach("ctrl1", "network", mgr)
    captured_cb["cb"]({"id": "e1"})
    assert sub_a.queue.get_nowait()["id"] == "e1"
    assert sub_b.queue.get_nowait()["id"] == "e1"


@pytest.mark.asyncio
async def test_detach_drops_subscriber_and_unregisters_when_last() -> None:
    pool = SubscriberPool()
    mgr = MagicMock()
    unsub = MagicMock()
    mgr.add_subscriber.return_value = unsub
    sub = await pool.attach("ctrl1", "network", mgr)
    await pool.detach("ctrl1", "network", sub)
    unsub.assert_called_once()


@pytest.mark.asyncio
async def test_queue_full_drops_event_for_slow_subscriber() -> None:
    pool = SubscriberPool(queue_maxsize=2)
    mgr = MagicMock()
    captured_cb = {}

    def fake_add_sub(cb):
        captured_cb["cb"] = cb
        return MagicMock()

    mgr.add_subscriber.side_effect = fake_add_sub
    sub = await pool.attach("ctrl1", "network", mgr)
    captured_cb["cb"]({"id": "e1"})
    captured_cb["cb"]({"id": "e2"})
    captured_cb["cb"]({"id": "e3"})  # this one drops
    items = [sub.queue.get_nowait() for _ in range(sub.queue.qsize())]
    assert [i["id"] for i in items] == ["e1", "e2"]
