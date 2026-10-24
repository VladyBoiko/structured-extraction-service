"""Common interface to the models.

The pipeline only knows about `Provider.generate(...)`. To add another provider
(OpenAI, Gemini, ...), write a subclass and register it in `make_provider`.
"""
import json
import os
import random
import time
from dataclasses import dataclass

import requests


class NonRetryableError(Exception):
    """An error that a retry cannot fix (e.g. the prompt does not fit into the context)."""


@dataclass
class LLMResult:
    text: str                 # model answer as a JSON string
    input_tokens: int = 0
    output_tokens: int = 0


class Provider:
    def check(self) -> None:
        """Check that the provider is reachable; raise if it is not."""

    def generate(self, system: str, user: str, schema: dict, temperature: float | None,
                 top_p: float | None, max_tokens: int, timeout: float) -> LLMResult:
        raise NotImplementedError


class AnthropicProvider(Provider):
    """Cloud model. Structured output: a forced tool call whose input schema is the extraction schema.

    temperature/top_p are sent only when set in the config: Claude Haiku 5.5 rejects sampling parameters.
    `effort` (low/medium/high/...) comes from the run's `options`; when unset, the model default applies.
    """

    def __init__(self, model: str, effort: str | None = None, **_):
        import anthropic

        key = os.getenv("ANTHROPIC_API_KEY")
        if not key or key == "your-key-here":
            raise RuntimeError("ANTHROPIC_API_KEY is not set: copy .env.example to .env and add your key")
        # max_retries=0: pipeline.py retries itself so that retries are counted and logged
        self.client = anthropic.Anthropic(api_key=key, max_retries=0)
        self.anthropic = anthropic
        self.model = model
        self.effort = effort

    def generate(self, system, user, schema, temperature, top_p, max_tokens, timeout) -> LLMResult:
        kwargs = {}
        if temperature is not None:
            kwargs["temperature"] = temperature
        if top_p is not None:
            kwargs["top_p"] = top_p
        if self.effort is not None:
            kwargs["output_config"] = {"effort": self.effort}
        try:
            resp = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system,
                messages=[{"role": "user", "content": user}],
                tools=[{
                    "name": "save_ticket",
                    "description": "Save the structured data extracted from the ticket.",
                    "input_schema": schema,
                }],
                tool_choice={"type": "tool", "name": "save_ticket"},
                timeout=timeout,
                **kwargs,
            )
        except self.anthropic.APIStatusError as e:
            # 4xx other than 408/409/429 is a request or key problem: a retry will not help
            if e.status_code < 500 and e.status_code not in (408, 409, 429):
                raise NonRetryableError(f"HTTP {e.status_code}: {e.message}") from e
            raise
        block = next((b for b in resp.content if b.type == "tool_use"), None)
        if block is None:  # e.g. stop_reason=max_tokens or refusal
            raise NonRetryableError(f"no tool call in response (stop_reason={resp.stop_reason})")
        return LLMResult(json.dumps(block.input, ensure_ascii=False),
                         resp.usage.input_tokens, resp.usage.output_tokens)


class OllamaProvider(Provider):
    """Local model via Ollama. Structured output: the `format` parameter with the schema.

    `num_ctx` is set explicitly because Ollama silently truncates prompts that do not fit.
    If prompt_eval_count + max_tokens > num_ctx, the answer is not trusted (NonRetryableError).
    """

    def __init__(self, model: str, num_ctx: int = 4096, **_):
        self.model = model
        self.num_ctx = num_ctx
        self.host = os.getenv("OLLAMA_HOST", "http://localhost:11434").rstrip("/")

    def check(self) -> None:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=5)
            r.raise_for_status()
        except Exception as e:
            raise RuntimeError(f"Ollama is not reachable at {self.host} (run `ollama serve`): {e}")
        names = [m["name"] for m in r.json().get("models", [])]
        if self.model not in names and f"{self.model}:latest" not in names:
            raise RuntimeError(f"Model {self.model} is not pulled: run `ollama pull {self.model}`")
        # Warm-up: an empty prompt only loads the model into memory (with the same num_ctx, otherwise it
        # reloads). Without it the first ticket pays the model load time, which distorts p95 latency.
        requests.post(f"{self.host}/api/generate",
                      json={"model": self.model, "prompt": "", "options": {"num_ctx": self.num_ctx}},
                      timeout=300).raise_for_status()

    def generate(self, system, user, schema, temperature, top_p, max_tokens, timeout) -> LLMResult:
        options = {"num_predict": max_tokens, "num_ctx": self.num_ctx}
        if temperature is not None:
            options["temperature"] = temperature
        if top_p is not None:
            options["top_p"] = top_p
        r = requests.post(
            f"{self.host}/api/chat",
            json={
                "model": self.model,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                "format": schema,
                "stream": False,
                "options": options,
            },
            timeout=timeout,
        )
        if 400 <= r.status_code < 500:  # e.g. model not found: a retry will not help
            raise NonRetryableError(f"HTTP {r.status_code}: {r.text[:200]}")
        r.raise_for_status()
        d = r.json()
        prompt_tokens, out_tokens = d.get("prompt_eval_count", 0), d.get("eval_count", 0)
        if prompt_tokens + max_tokens > self.num_ctx:
            raise NonRetryableError(
                f"prompt did not fit: {prompt_tokens} + {max_tokens} > num_ctx={self.num_ctx}")
        return LLMResult(d["message"]["content"], prompt_tokens, out_tokens)


class MockProvider(Provider):
    """Fake model to exercise the pipeline without any API. Not for real measurements."""

    def __init__(self, model: str, **_):
        self.flaky = "flaky" in model
        self.rng = random.Random(42)

    def generate(self, system, user, schema, temperature, top_p, max_tokens, timeout) -> LLMResult:
        time.sleep(0.01)
        if self.flaky:
            roll = self.rng.random()
            if roll < 0.15:
                raise TimeoutError("mock timeout")
            if roll < 0.35:
                return LLMResult('{"category": "payment"}', 100, 5)  # schema-invalid answer
        out = {
            "category": "other", "priority": "low", "sentiment": "neutral", "language": "en",
            "requested_action": "none", "needs_human": False, "summary": "Mock summary.",
            "product": {"name": None, "category": "unknown", "order_id": None},
        }
        return LLMResult(json.dumps(out), 300, 60)


def make_provider(kind: str, model: str, options: dict | None = None) -> Provider:
    providers = {"anthropic": AnthropicProvider, "ollama": OllamaProvider, "mock": MockProvider}
    if kind not in providers:
        raise ValueError(f"Unknown provider: {kind}. Available: {', '.join(providers)}")
    return providers[kind](model, **(options or {}))
