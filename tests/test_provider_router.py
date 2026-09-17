"""Test Provider Abstraction, Model Router, Retry & Token Telemetry."""
import json
import urllib.error
from unittest.mock import MagicMock, patch
import pytest

from owibot.provider import (
    BaseLLMProvider,
    LLMProvider,
    LLMResponse,
    ModelRouter,
    OpenAICompatibleProvider,
    TokenUsage,
)


class DummyProvider(BaseLLMProvider):
    def __init__(self, name: str, should_fail: bool = False, tokens: int = 100):
        super().__init__(model=name, base_url=f"http://test/{name}")
        self.should_fail = should_fail
        self.tokens = tokens
        self.call_count = 0

    def chat(self, messages, tools=None):
        self.call_count += 1
        if self.should_fail:
            raise RuntimeError(f"DummyProvider {self.model} intentional failure")
        return LLMResponse(
            text=f"Response from {self.model}",
            tool_calls=[],
            usage=TokenUsage(prompt_tokens=self.tokens, completion_tokens=20, total_tokens=self.tokens + 20),
            model=self.model,
            latency_s=0.05,
        )


def test_llm_response_dictionary_access():
    resp = LLMResponse(
        text="Hello world",
        tool_calls=[{"id": "c1", "name": "test", "arguments": {}}],
        usage=TokenUsage(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        model="gpt-test",
        latency_s=0.2,
    )
    assert resp["text"] == "Hello world"
    assert len(resp["tool_calls"]) == 1
    assert resp.get("model") == "gpt-test"
    assert resp.get("non_existent", "default") == "default"


def test_model_router_primary_success():
    primary = DummyProvider("primary")
    fallback = DummyProvider("fallback")
    router = ModelRouter(primary_provider=primary, fallback_providers=[fallback])

    response = router.chat([{"role": "user", "content": "Hi"}])
    assert response.text == "Response from primary"
    assert primary.call_count == 1
    assert fallback.call_count == 0

    assert router.total_requests == 1
    assert router.successful_requests == 1
    assert router.cumulative_usage.prompt_tokens == 100


def test_model_router_fallback_on_failure():
    primary = DummyProvider("primary", should_fail=True)
    fallback = DummyProvider("fallback", should_fail=False, tokens=50)
    router = ModelRouter(primary_provider=primary, fallback_providers=[fallback])

    response = router.chat([{"role": "user", "content": "Hi"}])
    assert response.text == "Response from fallback"
    assert primary.call_count == 1
    assert fallback.call_count == 1
    assert router.cumulative_usage.prompt_tokens == 50


def test_model_router_all_fail():
    primary = DummyProvider("primary", should_fail=True)
    fallback = DummyProvider("fallback", should_fail=True)
    router = ModelRouter(primary_provider=primary, fallback_providers=[fallback])

    with pytest.raises(RuntimeError) as exc_info:
        router.chat([{"role": "user", "content": "Hi"}])
    assert "DummyProvider fallback intentional failure" in str(exc_info.value)
    assert router.failed_requests == 1


def test_openai_compat_retry_on_transient_error():
    provider = OpenAICompatibleProvider(
        model="test-model",
        base_url="http://fake-api/v1",
        api_key="test-key",
        max_retries=2,
        initial_backoff_s=0.01,
    )

    mock_resp_body = json.dumps({
        "choices": [{"message": {"role": "assistant", "content": "Recovered!"}}],
        "usage": {"prompt_tokens": 12, "completion_tokens": 4, "total_tokens": 16},
    }).encode("utf-8")

    class MockHTTPResponse:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False
        def read(self):
            return mock_resp_body

    mock_fp = MagicMock()
    mock_fp.read.return_value = b'{"error":"Rate limited"}'
    rate_limit_err = urllib.error.HTTPError(
        url="http://fake-api/v1/chat/completions",
        code=429,
        msg="Too Many Requests",
        hdrs={},
        fp=mock_fp,
    )

    with patch("urllib.request.urlopen", side_effect=[rate_limit_err, MockHTTPResponse()]):
        resp = provider.chat([{"role": "user", "content": "Hello"}])
        assert resp.text == "Recovered!"
        assert resp.usage.total_tokens == 16


def test_llm_provider_facade_backward_compatibility():
    llm = LLMProvider(
        model="test-facade",
        base_url="http://localhost:11434/v1",
        api_key="test-key",
    )
    assert llm.model == "test-facade"
    assert isinstance(llm, ModelRouter)
