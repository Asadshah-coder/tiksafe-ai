"""Shared FastAPI dependencies."""

from ..core.config import Settings, get_settings
from ..services.ai_service import AINotConfigured, get_provider
from ..ai.base import AIProvider


def settings_dep() -> Settings:
    return get_settings()


async def ai_provider_dep() -> AIProvider:
    provider = get_provider()
    if provider is None:
        raise AINotConfigured(
            "AI features are currently unavailable. "
            "Set OPENAI_API_KEY or GEMINI_API_KEY to enable them."
        )
    return provider
