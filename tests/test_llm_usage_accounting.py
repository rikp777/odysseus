import asyncio
import json

import pytest

from src import billing_usage, llm_core


class _FakePostResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self.is_success = 200 <= status_code < 300
        self.text = text
        self._payload = payload

    def json(self):
        return self._payload if self._payload is not None else {
            "model": "gpt-4o-mini",
            "choices": [{"message": {"content": "hello"}}],
            "usage": {"prompt_tokens": 11, "completion_tokens": 7},
        }


class _FakeStreamResponse:
    status_code = 200

    def __init__(self, lines):
        self._lines = lines

    async def aiter_lines(self):
        for line in self._lines:
            yield line

    async def aread(self):
        return b""


class _FakeStreamContext:
    def __init__(self, lines):
        self._lines = lines

    async def __aenter__(self):
        return _FakeStreamResponse(self._lines)

    async def __aexit__(self, *args):
        return False


class _FakeClient:
    def __init__(self, lines=None):
        self._lines = lines or []

    async def post(self, *args, **kwargs):
        return _FakePostResponse()

    def stream(self, *args, **kwargs):
        return _FakeStreamContext(self._lines)


class _FakeSequenceClient:
    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = 0

    async def post(self, *args, **kwargs):
        self.calls += 1
        return self._responses.pop(0)


def _stub_network(monkeypatch, client):
    monkeypatch.setattr(llm_core, "_get_http_client", lambda: client)
    monkeypatch.setattr(llm_core, "_is_host_dead", lambda url: False)
    monkeypatch.setattr(llm_core, "_clear_host_dead", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_core, "note_model_activity", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_core, "_raise_if_cloud_spend_limited", lambda *args, **kwargs: None)
    monkeypatch.setattr(llm_core, "_cloud_spend_limit_error", lambda *args, **kwargs: None)


def test_record_llm_usage_requires_owner_or_context(monkeypatch):
    calls = []
    monkeypatch.setattr(billing_usage, "record_model_usage_from_metrics", lambda **kwargs: calls.append(kwargs))

    llm_core.record_llm_usage_safely(
        endpoint_url="https://api.openai.com/v1/chat/completions",
        model="gpt-4o-mini",
        metrics={"input_tokens": 1, "output_tokens": 2, "model": "gpt-4o-mini"},
    )

    assert calls == []


def test_record_llm_usage_forwards_context(monkeypatch):
    calls = []
    monkeypatch.setattr(billing_usage, "record_model_usage_from_metrics", lambda **kwargs: calls.append(kwargs))

    llm_core.record_llm_usage_safely(
        endpoint_url="https://api.openai.com/v1/chat/completions",
        model="selected-model",
        metrics={"input_tokens": 1, "output_tokens": 2, "model": "answered-model"},
        owner="rik",
        session_id="session-a",
        message_id="message-a",
    )

    assert calls == [{
        "owner": "rik",
        "session_id": "session-a",
        "message_id": "message-a",
        "endpoint_url": "https://api.openai.com/v1/chat/completions",
        "model": "answered-model",
        "metrics": {"input_tokens": 1, "output_tokens": 2, "model": "answered-model"},
    }]


@pytest.mark.asyncio
async def test_llm_call_async_records_real_provider_usage(monkeypatch):
    calls = []
    llm_core._response_cache.clear()
    _stub_network(monkeypatch, _FakeClient())
    monkeypatch.setattr(billing_usage, "record_model_usage_from_metrics", lambda **kwargs: calls.append(kwargs))

    result = await llm_core.llm_call_async(
        "https://api.openai.com/v1/chat/completions",
        "gpt-4o-mini",
        [{"role": "user", "content": "hi"}],
        headers={"Authorization": "Bearer test"},
        owner="rik",
        billing_context={"session_id": "session-a"},
        max_retries=1,
    )

    assert result == "hello"
    assert len(calls) == 1
    assert calls[0]["owner"] == "rik"
    assert calls[0]["session_id"] == "session-a"
    assert calls[0]["model"] == "gpt-4o-mini"
    assert calls[0]["metrics"]["input_tokens"] == 11
    assert calls[0]["metrics"]["output_tokens"] == 7
    assert calls[0]["metrics"]["usage_source"] == "real"


@pytest.mark.asyncio
async def test_llm_call_async_retries_transient_upstream_status(monkeypatch):
    llm_core._response_cache.clear()
    client = _FakeSequenceClient([
        _FakePostResponse(status_code=502, text="bad gateway"),
        _FakePostResponse(),
    ])
    _stub_network(monkeypatch, client)

    async def _no_sleep(_delay):
        return None

    monkeypatch.setattr(llm_core.asyncio, "sleep", _no_sleep)

    result = await llm_core.llm_call_async(
        "https://api.openai.com/v1/chat/completions",
        "gpt-4o-mini",
        [{"role": "user", "content": "hi"}],
        headers={"Authorization": "Bearer test"},
        owner="rik",
        max_retries=2,
    )

    assert result == "hello"
    assert client.calls == 2


def test_stream_llm_records_usage_once_for_owned_call(monkeypatch):
    calls = []
    lines = [
        'data: ' + json.dumps({"choices": [{"delta": {"content": "hi"}}]}),
        'data: ' + json.dumps({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 5}}),
        "data: [DONE]",
    ]
    _stub_network(monkeypatch, _FakeClient(lines))
    monkeypatch.setattr(billing_usage, "record_model_usage_from_metrics", lambda **kwargs: calls.append(kwargs))

    async def run():
        return [chunk async for chunk in llm_core.stream_llm(
            "https://api.openai.com/v1/chat/completions",
            "gpt-4o-mini",
            [{"role": "user", "content": "hi"}],
            headers={"Authorization": "Bearer test"},
            owner="rik",
            billing_context={"session_id": "session-a"},
        )]

    chunks = asyncio.run(run())

    assert chunks[-1] == "data: [DONE]\n\n"
    assert len(calls) == 1
    assert calls[0]["owner"] == "rik"
    assert calls[0]["session_id"] == "session-a"
    assert calls[0]["metrics"]["input_tokens"] == 3
    assert calls[0]["metrics"]["output_tokens"] == 5


def test_stream_llm_record_false_prevents_double_counting(monkeypatch):
    calls = []
    lines = [
        'data: ' + json.dumps({"choices": [{"delta": {"content": "hi"}}]}),
        'data: ' + json.dumps({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 5}}),
        "data: [DONE]",
    ]
    _stub_network(monkeypatch, _FakeClient(lines))
    monkeypatch.setattr(billing_usage, "record_model_usage_from_metrics", lambda **kwargs: calls.append(kwargs))

    async def run():
        usage_events = []
        async for chunk in llm_core.stream_llm(
            "https://api.openai.com/v1/chat/completions",
            "gpt-4o-mini",
            [{"role": "user", "content": "hi"}],
            headers={"Authorization": "Bearer test"},
            owner="rik",
            billing_context={"record": False},
        ):
            if chunk.startswith("data: ") and '"type": "usage"' in chunk:
                usage_events.append(json.loads(chunk[6:])["data"])
        return usage_events

    usage_events = asyncio.run(run())

    assert usage_events == [{"input_tokens": 3, "output_tokens": 5}]
    assert calls == []
