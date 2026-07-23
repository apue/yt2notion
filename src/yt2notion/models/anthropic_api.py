"""Anthropic API text-call adapter."""

from __future__ import annotations

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None  # type: ignore[assignment]


class AnthropicAPIError(Exception):
    """Raised when the Anthropic adapter cannot complete a call."""


MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


class AnthropicAPICaller:
    """One-shot LLM caller using the Anthropic Python SDK."""

    def __init__(self, api_key: str, model: str = "opus") -> None:
        if _anthropic is None:
            raise AnthropicAPIError(
                "anthropic package not installed. Run: uv sync --extra anthropic"
            )
        self.client = _anthropic.Anthropic(api_key=api_key)
        self.model = MODEL_MAP.get(model, model)

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as exc:
            raise AnthropicAPIError(f"Anthropic API call failed: {exc}") from exc
