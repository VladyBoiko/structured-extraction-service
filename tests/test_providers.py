from types import SimpleNamespace

import pytest

from src.providers import AnthropicProvider, NonRetryableError, OllamaProvider


def test_ollama_4xx_is_not_retried(monkeypatch):
    resp = SimpleNamespace(status_code=404, text="model not found")
    monkeypatch.setattr("src.providers.requests.post", lambda *a, **k: resp)
    with pytest.raises(NonRetryableError):
        OllamaProvider("qwen2.5:3b").generate("s", "u", {}, 0.0, 1.0, 100, 1)


@pytest.fixture
def anthropic_provider(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    p = AnthropicProvider("claude-haiku-5-5", effort="low")
    calls = []

    def fake_create(**kwargs):
        calls.append(kwargs)
        return SimpleNamespace(content=[], stop_reason="max_tokens", usage=None)

    monkeypatch.setattr(p.client.messages, "create", fake_create)
    return p, calls


def test_anthropic_without_tool_call_is_not_retried(anthropic_provider):
    p, _ = anthropic_provider
    with pytest.raises(NonRetryableError, match="max_tokens"):
        p.generate("s", "u", {}, None, None, 100, 1)


def test_anthropic_sends_effort_and_no_sampling(anthropic_provider):
    p, calls = anthropic_provider
    with pytest.raises(NonRetryableError):
        p.generate("s", "u", {}, None, None, 100, 1)
    assert calls[0]["output_config"] == {"effort": "low"}
    assert "temperature" not in calls[0] and "top_p" not in calls[0]
