from __future__ import annotations

from typing import Optional

from .base import BaseLLMProvider, LLMResponse, TokenUsage
from .codex_cli import CodexCLIProvider
from .openai_compat import OpenAICompatibleProvider
from .router import ModelRouter


def create_provider(
    model: str,
    api_key: str = "local",
    base_url: str = "http://127.0.0.1:11434/v1",
    cwd: Optional[str] = None,
    timeout_s: float = 300.0,
    max_retries: int = 3,
) -> BaseLLMProvider:
    if base_url.strip().lower() == "codex":
        return CodexCLIProvider(model=model, cwd=cwd)

    return OpenAICompatibleProvider(
        model=model,
        base_url=base_url,
        api_key=api_key,
        timeout_s=timeout_s,
        max_retries=max_retries,
    )


class LLMProvider(ModelRouter):
    """Facade class untuk backward-compatibility penuh dengan kode existing."""

    def __init__(
        self,
        model: str,
        api_key: str = "local",
        base_url: str = "http://127.0.0.1:11434/v1",
        cwd: Optional[str] = None,
        timeout_s: float = 300.0,
        max_retries: int = 3,
        fallback_providers: list[BaseLLMProvider] | None = None,
    ):
        primary = create_provider(
            model=model,
            api_key=api_key,
            base_url=base_url,
            cwd=cwd,
            timeout_s=timeout_s,
            max_retries=max_retries,
        )
        super().__init__(primary_provider=primary, fallback_providers=fallback_providers)
