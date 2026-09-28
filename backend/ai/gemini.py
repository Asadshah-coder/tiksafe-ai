"""Google Gemini provider (plain httpx against the generateContent REST API)."""

import httpx

from ..core.logging import get_logger
from .base import AIProvider, AIProviderError

log = get_logger("ai.gemini")


class GeminiProvider(AIProvider):
    name = "gemini"

    def __init__(
        self, api_key: str, model: str = "gemini-2.0-flash", timeout: int = 60
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(self, system: str, user: str) -> str:
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent"
        )
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    url,
                    params={"key": self.api_key},
                    json={
                        "systemInstruction": {"parts": [{"text": system}]},
                        "contents": [{"parts": [{"text": user}]}],
                        "generationConfig": {"temperature": 0.7},
                    },
                )
        except httpx.HTTPError as exc:
            raise AIProviderError(
                "network_error", "Could not reach the AI provider. Try again shortly."
            ) from exc

        if resp.status_code in (400, 401, 403):
            raise AIProviderError(
                "auth", "The configured Gemini API key was rejected."
            )
        if resp.status_code == 429:
            raise AIProviderError(
                "rate_limited",
                "The AI provider is rate-limited right now. Try again shortly.",
            )
        if resp.status_code >= 400:
            log.warning("Gemini error %s: %s", resp.status_code, resp.text[:300])
            raise AIProviderError(
                "provider_error", "The AI provider returned an error. Try again shortly."
            )
        try:
            data = resp.json()
            return str(
                data["candidates"][0]["content"]["parts"][0]["text"]
            ).strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise AIProviderError(
                "provider_error", "The AI provider returned an unexpected response."
            ) from exc
