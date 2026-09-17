from __future__ import annotations

import logging
from typing import Any, Optional

from .base import BaseLLMProvider, LLMResponse, TokenUsage

logger = logging.getLogger("owibot.provider")


class ModelRouter(BaseLLMProvider):
    def __init__(
        self,
        primary_provider: BaseLLMProvider,
        fallback_providers: list[BaseLLMProvider] | None = None,
        role_providers: dict[str, BaseLLMProvider] | None = None,
    ):
        super().__init__(
            model=primary_provider.model,
            base_url=primary_provider.base_url,
            api_key=primary_provider.api_key,
        )
        self.primary = primary_provider
        self.fallbacks = fallback_providers or []
        self.roles = role_providers or {}

        # Telemetri kumulatif
        self.cumulative_usage = TokenUsage()
        self.total_requests: int = 0
        self.successful_requests: int = 0
        self.failed_requests: int = 0

    def get_provider_for_role(self, role: str) -> BaseLLMProvider:
        return self.roles.get(role, self.primary)

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None, role: str | None = None) -> LLMResponse:
        self.total_requests += 1
        target_provider = self.get_provider_for_role(role) if role else self.primary

        chain = [target_provider] + [p for p in self.fallbacks if p != target_provider]
        last_exception: Exception | None = None

        for provider in chain:
            try:
                response = provider.chat(messages, tools=tools)

                # Update telemetri
                self.successful_requests += 1
                self.cumulative_usage.prompt_tokens += response.usage.prompt_tokens
                self.cumulative_usage.completion_tokens += response.usage.completion_tokens
                self.cumulative_usage.total_tokens += response.usage.total_tokens

                return response
            except Exception as exc:
                last_exception = exc
                logger.warning(
                    "Provider %s (%s) gagal: %s. Mencoba fallback...",
                    provider.model,
                    provider.base_url,
                    exc,
                )

        self.failed_requests += 1
        if last_exception:
            raise last_exception
        raise RuntimeError("Semua provider gagal memproses permintaan.")
