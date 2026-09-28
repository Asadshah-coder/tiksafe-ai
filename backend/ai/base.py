"""AI provider abstraction. Add a new provider by subclassing AIProvider."""

from abc import ABC, abstractmethod


class AIProviderError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code
        self.message = message
        super().__init__(message)


class AIProvider(ABC):
    name: str = "base"

    @abstractmethod
    async def complete(self, system: str, user: str) -> str:
        """Return the model's text reply for a system+user prompt pair."""
