"""AI toolkit orchestration: captions, hashtags, summaries, translation.

Works without any API key — every public function raises AINotConfigured,
which the API turns into a friendly 503 instead of a crash.
"""

from __future__ import annotations

import json
import re

from ..ai.base import AIProvider, AIProviderError
from ..ai.gemini import GeminiProvider
from ..ai.openai import OpenAIProvider
from ..core.config import get_settings
from ..core.logging import get_logger

log = get_logger("ai_service")

CAPTION_STYLES = [
    "professional",
    "viral",
    "storytelling",
    "short",
    "emotional",
    "educational",
]

LANGUAGE_NAMES = {
    "en": "English",
    "ur": "Urdu",
    "roman_ur": "Roman Urdu (Urdu written in Latin script)",
}

AI_UNAVAILABLE_MESSAGE = (
    "AI features are currently unavailable. "
    "Set OPENAI_API_KEY or GEMINI_API_KEY to enable them."
)


class AINotConfigured(Exception):
    """Raised when AI features are requested but no provider key is configured."""


def get_provider() -> AIProvider | None:
    settings = get_settings()
    if settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key, settings.openai_model)
    if settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key, settings.gemini_model)
    return None


def ai_available() -> bool:
    return get_provider() is not None


async def _require_provider() -> AIProvider:
    provider = get_provider()
    if provider is None:
        raise AINotConfigured(AI_UNAVAILABLE_MESSAGE)
    return provider


def _parse_json_object(text: str):
    """Extract the first JSON object from model output; None on failure."""
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else None
    except (json.JSONDecodeError, ValueError):
        pass
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else None
        except (json.JSONDecodeError, ValueError):
            return None
    return None


def _clean_hashtag(tag: str) -> str:
    tag = re.sub(r"\s+", "", str(tag).strip().lstrip("#"))
    tag = re.sub(r"[^\w\u0600-\u06FF]", "", tag)
    return f"#{tag}" if tag else ""


def _clean_hashtag_list(raw) -> list[str]:
    seen: set[str] = set()
    cleaned: list[str] = []
    items = raw if isinstance(raw, list) else []
    for item in items:
        tag = _clean_hashtag(item)
        if tag and tag.lower() not in seen and len(tag) > 1:
            seen.add(tag.lower())
            cleaned.append(tag)
        if len(cleaned) >= 10:
            break
    return cleaned


async def generate_captions(
    topic: str, language: str = "en", styles: list[str] | None = None
) -> dict[str, str]:
    provider = await _require_provider()
    wanted = [s for s in (styles or CAPTION_STYLES) if s in CAPTION_STYLES] or CAPTION_STYLES
    lang_name = LANGUAGE_NAMES.get(language, "English")
    system = (
        "You are a social-media copywriter. Write captions using ONLY the facts "
        "provided about the video. Never invent facts, names, events, or statistics "
        "about the video."
    )
    user = (
        f"Video topic/title: {topic}\n"
        f"Language: {lang_name}\n"
        f"Write one caption for each of these styles: {', '.join(wanted)}.\n"
        'Reply with ONLY a JSON object mapping style name to caption text, '
        'for example {"professional": "...", "viral": "..."}.'
    )
    try:
        raw = await provider.complete(system, user)
    except AIProviderError as exc:
        log.warning("caption provider error: %s", exc.code)
        raise
    parsed = _parse_json_object(raw)
    if parsed:
        result = {
            style: str(parsed.get(style, "")).strip()
            for style in wanted
            if str(parsed.get(style, "")).strip()
        }
        if result:
            return result
    return {"general": raw.strip()}


async def generate_hashtags(topic: str, language: str = "en") -> dict[str, list[str]]:
    provider = await _require_provider()
    lang_name = LANGUAGE_NAMES.get(language, "English")
    system = (
        "You are a social-media strategist. Suggest hashtags that are directly "
        "relevant to the given topic. Never suggest spammy or unrelated hashtags."
    )
    user = (
        f"Topic: {topic}\nLanguage: {lang_name}\n"
        "Suggest hashtags in three groups: primary (most relevant), niche "
        "(community-specific), and broad (wide reach). "
        'Reply with ONLY JSON like {"primary": [...], "niche": [...], "broad": [...]}.'
    )
    try:
        raw = await provider.complete(system, user)
    except AIProviderError as exc:
        log.warning("hashtag provider error: %s", exc.code)
        raise
    parsed = _parse_json_object(raw) or {}
    return {
        "primary": _clean_hashtag_list(parsed.get("primary")),
        "niche": _clean_hashtag_list(parsed.get("niche")),
        "broad": _clean_hashtag_list(parsed.get("broad")),
    }


async def summarize_text(text: str, language: str = "en") -> dict:
    provider = await _require_provider()
    lang_name = LANGUAGE_NAMES.get(language, "English")
    system = (
        "You summarize video transcripts. Base everything strictly on the "
        "provided text; do not invent details that are not in it."
    )
    user = (
        f"Language: {lang_name}\n"
        f"Transcript:\n{text[:6000]}\n\n"
        "Summarize it. "
        'Reply with ONLY JSON like {"summary": "...", "key_points": [...], '
        '"topics": [...], "keywords": [...]}.'
    )
    try:
        raw = await provider.complete(system, user)
    except AIProviderError as exc:
        log.warning("summarize provider error: %s", exc.code)
        raise
    parsed = _parse_json_object(raw) or {}
    key_points = [str(p).strip() for p in parsed.get("key_points", []) if str(p).strip()][:8]
    topics = [str(p).strip() for p in parsed.get("topics", []) if str(p).strip()][:8]
    keywords = [str(p).strip() for p in parsed.get("keywords", []) if str(p).strip()][:12]
    return {
        "summary": str(parsed.get("summary", "")).strip() or raw.strip()[:1000],
        "key_points": key_points,
        "topics": topics,
        "keywords": keywords,
    }


async def translate_text(text: str, target: str) -> str:
    provider = await _require_provider()
    target_name = LANGUAGE_NAMES.get(target, "English")
    system = (
        "You are a translator. Translate the user's text accurately, keeping "
        "the tone and meaning. Reply with only the translation, no commentary."
    )
    user = f"Translate the following text to {target_name}:\n\n{text}"
    try:
        return await provider.complete(system, user)
    except AIProviderError as exc:
        log.warning("translate provider error: %s", exc.code)
        raise
