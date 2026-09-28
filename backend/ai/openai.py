"""OpenAI chat-completions provider (plain httpx, no heavy SDK)."""

import httpx

from ..core.logging import get_logger
from .base import AIProvider, AIProviderError

log = get_logger("ai.openai")


class OpenAIProvider(AIProvider):
    name = "openai"

    def __init__(
        self, api_key: str, model: str = "gpt-4o-mini", timeout: int = 60
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.timeout = timeout

    async def complete(self, system: str, user: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={
                        "model": self.model,
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user", "content": user},
                        ],
                        "temperature": 0.7,
                    },
                )
        except httpx.HTTPError as exc:
            raise AIProviderError(
                "network_error", "Could not reach the AI provider. Try again shortly."
            ) from exc

        if resp.status_code == 401:
            raise AIProviderError(
                "auth", "The configured OpenAI API key was rejected."
            )
        if resp.status_code == 429:
            raise AIProviderError(
                "rate_limited",
                "The AI provider is rate-limited right now. Try again shortly.",
            )
        if resp.status_code >= 400:
            log.warning("OpenAI error %s: %s", resp.status_code, resp.text[:300])
            raise AIProviderError(
                "provider_error", "The AI provider returned an error. Try again shortly."
            )
        try:
            data = resp.json()
            return str(data["choices"][0]["message"]["content"]).strip()
        except (KeyError, IndexError, ValueError) as exc:
            raise AIProviderError(
                "provider_error", "The AI provider returned an unexpected response."
            ) from exc
