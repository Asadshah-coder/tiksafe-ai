"""AI service tests with a stub provider — no real API keys, no network."""

import asyncio

import pytest

from backend.ai.base import AIProvider
from backend.services import ai_service
from backend.services.ai_service import AINotConfigured


class StubProvider(AIProvider):
    name = "stub"

    def __init__(self, text: str) -> None:
        self.text = text

    async def complete(self, system: str, user: str) -> str:
        return self.text


def _stub(monkeypatch, text: str):
    monkeypatch.setattr(
        "backend.services.ai_service.get_provider",
        lambda: StubProvider(text),
    )


def test_no_provider_without_keys():
    assert ai_service.get_provider() is None
    assert ai_service.ai_available() is False


def test_generate_captions_raises_without_keys():
    with pytest.raises(AINotConfigured):
        asyncio.run(ai_service.generate_captions("cats"))


def test_generate_captions_parses_json(monkeypatch):
    _stub(monkeypatch, '{"professional": "Hello world", "viral": "You NEED this"}')
    result = asyncio.run(
        ai_service.generate_captions("cats", "en", ["professional", "viral"])
    )
    assert result == {
        "professional": "Hello world",
        "viral": "You NEED this",
    }


def test_generate_captions_falls_back_to_raw_text(monkeypatch):
    _stub(monkeypatch, "Just a plain caption without JSON.")
    result = asyncio.run(ai_service.generate_captions("cats"))
    assert result == {"general": "Just a plain caption without JSON."}


def test_generate_captions_ignores_unknown_styles(monkeypatch):
    _stub(monkeypatch, '{"professional": "Hi"}')
    result = asyncio.run(
        ai_service.generate_captions("cats", styles=["professional", "bogus"])
    )
    assert result == {"professional": "Hi"}


def test_generate_hashtags_cleans_and_dedupes(monkeypatch):
    _stub(
        monkeypatch,
        '{"primary": ["#Cats", "cats", "#cat lover", "#"], '
        '"niche": ["#catsoftiktok"], "broad": "not-a-list"}',
    )
    result = asyncio.run(ai_service.generate_hashtags("cats"))
    assert result["primary"] == ["#Cats", "#catlover"]
    assert result["niche"] == ["#catsoftiktok"]
    assert result["broad"] == []


def test_summarize_parses_structured_output(monkeypatch):
    _stub(
        monkeypatch,
        '{"summary": "A cat video.", "key_points": ["Cats are cute"], '
        '"topics": ["pets"], "keywords": ["cat", "funny"]}',
    )
    result = asyncio.run(ai_service.summarize_text("transcript here"))
    assert result["summary"] == "A cat video."
    assert result["key_points"] == ["Cats are cute"]
    assert result["topics"] == ["pets"]
    assert result["keywords"] == ["cat", "funny"]


def test_translate_returns_provider_text(monkeypatch):
    _stub(monkeypatch, "ہیلو دنیا")
    result = asyncio.run(ai_service.translate_text("hello world", "ur"))
    assert result == "ہیلو دنیا"


def test_parse_json_object_handles_wrapped_json():
    parsed = ai_service._parse_json_object(
        'Here you go:\n{"a": 1}\nThanks!'
    )
    assert parsed == {"a": 1}
    assert ai_service._parse_json_object("no json here") is None
