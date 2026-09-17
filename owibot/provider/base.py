from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class TokenUsage:
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0

    def to_dict(self) -> dict[str, int]:
        return {
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "total_tokens": self.total_tokens,
        }


@dataclass
class LLMResponse:
    text: str = ""
    tool_calls: list[dict[str, Any]] = field(default_factory=list)
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""
    latency_s: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "tool_calls": self.tool_calls,
            "usage": self.usage.to_dict(),
            "model": self.model,
            "latency_s": self.latency_s,
        }

    def __getitem__(self, key: str) -> Any:
        # Menjaga backward-compatibility dengan dictionary akses response["text"] / response["tool_calls"]
        if key == "text":
            return self.text
        if key == "tool_calls":
            return self.tool_calls
        if key == "usage":
            return self.usage
        if key == "model":
            return self.model
        if key == "latency_s":
            return self.latency_s
        raise KeyError(key)

    def get(self, key: str, default: Any = None) -> Any:
        try:
            return self[key]
        except KeyError:
            return default


class BaseLLMProvider(ABC):
    def __init__(self, model: str, base_url: str, api_key: str = ""):
        self.model = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    @abstractmethod
    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        """Mengirim percakapan ke model dan mengembalikan LLMResponse."""
        pass
