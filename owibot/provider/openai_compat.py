from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, Optional

from .base import BaseLLMProvider, LLMResponse, TokenUsage

TRANSIENT_HTTP_CODES = {429, 500, 502, 503, 504}


def _extract_text_content(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        chunks = [
            str(item.get("text", ""))
            for item in content
            if isinstance(item, dict) and "text" in item
        ]
        return "".join(chunks)
    if content is None:
        return ""
    return str(content)


def _safe_parse_args(raw_value: object) -> dict:
    if isinstance(raw_value, dict):
        return raw_value
    if isinstance(raw_value, str):
        try:
            parsed = json.loads(raw_value)
            return parsed if isinstance(parsed, dict) else {"raw": raw_value}
        except (json.JSONDecodeError, ValueError):
            return {"raw": raw_value}
    return {}


class OpenAICompatibleProvider(BaseLLMProvider):
    def __init__(
        self,
        model: str,
        base_url: str,
        api_key: str = "local",
        timeout_s: float = 300.0,
        max_retries: int = 3,
        initial_backoff_s: float = 1.0,
    ):
        super().__init__(model=model, base_url=base_url, api_key=api_key)
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.initial_backoff_s = initial_backoff_s

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None) -> LLMResponse:
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "temperature": 0.2,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key or 'local'}",
        }

        request_data = json.dumps(payload).encode("utf-8")
        url = f"{self.base_url}/chat/completions"

        start_time = time.monotonic()
        attempts = 0
        backoff = self.initial_backoff_s

        while True:
            attempts += 1
            request = urllib.request.Request(url=url, data=request_data, headers=headers, method="POST")

            try:
                with urllib.request.urlopen(request, timeout=self.timeout_s) as response:
                    body = json.loads(response.read().decode("utf-8"))
                    choice_message = body["choices"][0]["message"]
                    usage_data = body.get("usage", {})

                latency = round(time.monotonic() - start_time, 3)

                token_usage = TokenUsage(
                    prompt_tokens=int(usage_data.get("prompt_tokens", 0) or 0),
                    completion_tokens=int(usage_data.get("completion_tokens", 0) or 0),
                    total_tokens=int(usage_data.get("total_tokens", 0) or 0),
                )

                raw_tool_calls = choice_message.get("tool_calls", [])
                parsed_calls = [
                    {
                        "id": call["id"],
                        "name": call["function"]["name"],
                        "arguments": _safe_parse_args(call["function"].get("arguments", "{}")),
                    }
                    for call in raw_tool_calls
                ]

                return LLMResponse(
                    text=_extract_text_content(choice_message.get("content")),
                    tool_calls=parsed_calls,
                    usage=token_usage,
                    model=str(body.get("model", self.model)),
                    latency_s=latency,
                )

            except urllib.error.HTTPError as http_err:
                is_transient = http_err.code in TRANSIENT_HTTP_CODES
                if is_transient and attempts <= self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue

                error_body = ""
                try:
                    error_body = http_err.read().decode("utf-8", errors="ignore")[:300]
                except Exception:
                    pass
                raise RuntimeError(
                    f"HTTP {http_err.code} saat memanggil {url}: {http_err.reason}. Detail: {error_body}"
                ) from http_err

            except (urllib.error.URLError, TimeoutError) as net_err:
                if attempts <= self.max_retries:
                    time.sleep(backoff)
                    backoff *= 2
                    continue
                raise RuntimeError(f"Gagal terhubung ke {url}: {net_err}") from net_err
