"""Topic sends without a reply target of their own (background-process notices, cron
deliveries, queued follow-ups) must reply in thread: Feishu's create API has no
``thread_id`` receive type and rejects it with 99992402 (#78975)."""
import asyncio
import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from gateway.config import PlatformConfig
from plugins.platforms.feishu.adapter import _FEISHU_THREAD_ANCHOR_CACHE_SIZE, FeishuAdapter


def _ok(message_id):
    return SimpleNamespace(success=lambda: True, data=SimpleNamespace(message_id=message_id))


def _rejected(code):
    return SimpleNamespace(success=lambda: False, code=code, msg="rejected", data=None)


class _MessageAPI:
    def __init__(self, replies=(), thread_items=()):
        self._replies = list(replies)
        self._thread_items = list(thread_items)
        self.replies, self.creates, self.lists = [], [], []

    def reply(self, request):
        self.replies.append(request)
        return self._replies.pop(0) if self._replies else _ok(f"om_sent_{len(self.replies)}")

    def create(self, request):
        self.creates.append(request)
        return _ok("om_created")

    async def fetch_thread_message(self, thread_id):
        self.lists.append(thread_id)
        return self._thread_items[0] if self._thread_items else None


@pytest.fixture
def make_adapter():
    with patch.dict(os.environ, {}, clear=True):
        def _make(api):
            adapter = FeishuAdapter(PlatformConfig())
            adapter._client = SimpleNamespace(im=SimpleNamespace(v1=SimpleNamespace(message=api)))

            async def _direct(func, *args):
                return func(*args)

            adapter._run_blocking = _direct
            adapter._fetch_last_message_in_thread = api.fetch_thread_message  # SDK-free topic lookup
            return adapter

        yield _make


def _send(adapter, *, reply_to=None, metadata=None):
    return asyncio.run(adapter._send_raw_message(
        chat_id="oc_chat", msg_type="text", payload=json.dumps({"text": "done"}), reply_to=reply_to, metadata=metadata,
    ))


def test_replies_in_thread_to_the_latest_inbound_message(make_adapter):
    api = _MessageAPI()
    adapter = make_adapter(api)
    adapter._remember_thread_anchor("omt_topic", "om_user_ask")

    response = _send(adapter, metadata={"thread_id": "omt_topic"})

    assert response.success()
    assert api.creates == [] and api.lists == []
    assert [r.message_id for r in api.replies] == ["om_user_ask"]
    assert api.replies[0].request_body.reply_in_thread is True


def test_own_sent_reply_becomes_the_next_anchor(make_adapter):
    api = _MessageAPI()
    adapter = make_adapter(api)

    _send(adapter, reply_to="om_user_ask", metadata={"thread_id": "omt_topic"})
    _send(adapter, metadata={"thread_id": "omt_topic"})

    assert [r.message_id for r in api.replies] == ["om_user_ask", "om_sent_1"]
    assert api.creates == []


def test_reads_the_topic_when_no_message_was_seen(make_adapter):
    api = _MessageAPI(thread_items=["om_topic_root"])
    adapter = make_adapter(api)

    _send(adapter, metadata={"thread_id": "omt_topic"})

    assert api.lists == ["omt_topic"]
    assert [r.message_id for r in api.replies] == ["om_topic_root"]
    assert api.replies[0].request_body.reply_in_thread is True
    assert api.creates == []


def test_withdrawn_anchor_is_replaced_by_one_read_from_the_topic(make_adapter):
    api = _MessageAPI(replies=[_rejected(230011)], thread_items=["om_topic_root"])
    adapter = make_adapter(api)
    adapter._remember_thread_anchor("omt_topic", "om_withdrawn")

    response = _send(adapter, metadata={"thread_id": "omt_topic"})

    assert response.success()
    assert [r.message_id for r in api.replies] == ["om_withdrawn", "om_topic_root"]
    assert adapter._thread_anchors["omt_topic"] == "om_sent_2"


def test_other_reply_failures_are_returned_without_a_second_attempt(make_adapter):
    api = _MessageAPI(replies=[_rejected(230001)], thread_items=["om_topic_root"])
    adapter = make_adapter(api)
    adapter._remember_thread_anchor("omt_topic", "om_user_ask")

    response = _send(adapter, metadata={"thread_id": "omt_topic"})

    assert response.code == 230001
    assert len(api.replies) == 1 and api.lists == [] and api.creates == []


def test_topic_without_any_reachable_message_goes_to_the_chat_never_to_thread_id(make_adapter):
    api = _MessageAPI(thread_items=[])
    adapter = make_adapter(api)

    _send(adapter, metadata={"thread_id": "omt_topic"})

    assert api.replies == []
    assert len(api.creates) == 1
    assert api.creates[0].receive_id_type == "chat_id"
    assert api.creates[0].request_body.receive_id == "oc_chat"


def test_anchor_cache_is_bounded(make_adapter):
    adapter = make_adapter(_MessageAPI())
    for i in range(_FEISHU_THREAD_ANCHOR_CACHE_SIZE + 5):
        adapter._remember_thread_anchor(f"omt_{i}", f"om_{i}")

    assert len(adapter._thread_anchors) == _FEISHU_THREAD_ANCHOR_CACHE_SIZE
    assert "omt_0" not in adapter._thread_anchors
    assert adapter._thread_anchors[f"omt_{_FEISHU_THREAD_ANCHOR_CACHE_SIZE + 4}"] == f"om_{_FEISHU_THREAD_ANCHOR_CACHE_SIZE + 4}"
