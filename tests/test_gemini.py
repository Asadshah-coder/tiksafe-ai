"""Gemini provider tests: model fallback on 404, auth errors stay terminal."""

import asyncio

import pytest

from backend.ai.base import AIProviderError
from backend.ai.gemini import DEFAULT_MODEL, GeminiProvider


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text

    def json(self):
        return self._payload


class _FakeClient:
    """Async context manager mimicking httpx.AsyncClient with canned responses."""

    def __init__(self, responses: list[_FakeResponse], seen_urls: list):
        self._responses = responses  # shared across retries; do not copy
        self._seen_urls = seen_urls

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def post(self, url, params=None, json=None):
        self._seen_urls.append(url)
        return self._responses.pop(0)


def _patch_client(monkeypatch, responses):
    seen: list = []

    def _factory(*args, **kwargs):
        return _FakeClient(responses, seen)

    monkeypatch.setattr("backend.ai.gemini.httpx.AsyncClient", _factory)
    return seen


def _ok_response(text: str = "hello"):
    return _FakeResponse(
        200, {"candidates": [{"content": {"parts": [{"text": text}]}}]}
    )


def test_default_model_is_current():
    assert DEFAULT_MODEL == "gemini-3.8-flash"
    assert GeminiProvider("key").model == "gemini-3.8-flash"


def test_successful_call_uses_configured_model(monkeypatch):
    seen = _patch_client(monkeypatch, [_ok_response("hi")])
    out = asyncio.run(GeminiProvider("key").complete("sys", "user"))
    assert out == "hi"
    assert len(seen) == 1
    assert "gemini-3.8-flash" in seen[0]


def test_404_falls_back_to_next_model(monkeypatch):
    seen = _patch_client(
        monkeypatch, [_FakeResponse(404, text="not found"), _ok_response("fallback ok")]
    )
    out = asyncio.run(GeminiProvider("key", model="retired-model").complete("s", "u"))
    assert out == "fallback ok"
    assert len(seen) == 2
    assert "retired-model" in seen[0]
    assert "gemini-3.8-flash" in seen[1]


def test_401_does_not_fall_back(monkeypatch):
    seen = _patch_client(monkeypatch, [_FakeResponse(401, text="bad key")])
    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(GeminiProvider("key").complete("s", "u"))
    assert exc_info.value.code == "auth"
    assert len(seen) == 1  # no fallback attempts on auth errors


def test_all_models_404_raises_provider_error(monkeypatch):
    responses = [_FakeResponse(404, text="gone") for _ in range(3)]
    seen = _patch_client(monkeypatch, responses)
    with pytest.raises(AIProviderError) as exc_info:
        asyncio.run(GeminiProvider("key").complete("s", "u"))
    assert exc_info.value.code == "provider_error"
    assert len(seen) == 3  # default model + 2 remaining fallbacks
