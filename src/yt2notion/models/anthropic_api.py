"""Anthropic API LLM backend. Requires API key, pay per token."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.models._parsers import parse_chinese_markdown, parse_summary_json
from yt2notion.prompts import load_prompt

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, Summary, VideoMeta

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None  # type: ignore[assignment]


class AnthropicAPIError(Exception):
    """Raised when Anthropic API call fails."""


# Model name mapping: short alias → full model ID
MODEL_MAP = {
    "sonnet": "claude-sonnet-4-6",
    "opus": "claude-opus-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


class AnthropicAPIModel:
    """LLM backend using the Anthropic Python SDK."""

    def __init__(
        self,
        api_key: str,
        summarize_model: str = "sonnet",
        translate_model: str = "opus",
    ) -> None:
        if _anthropic is None:
            raise AnthropicAPIError(
                "anthropic package not installed. Run: uv sync --extra anthropic"
            )
        self.client = _anthropic.Anthropic(api_key=api_key)
        self.summarize_model = MODEL_MAP.get(summarize_model, summarize_model)
        self.translate_model = MODEL_MAP.get(translate_model, translate_model)

    def summarize(
        self, transcript: str, metadata: VideoMeta, *, prompt_name: str = "summarize"
    ) -> Summary:
        """Produce a structured summary with timestamps."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\nURL: {metadata.url}\n\n{transcript}"
        )
        raw = self._call_api(system_prompt, user_prompt, self.summarize_model)
        return parse_summary_json(raw)

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        system_prompt = load_prompt("chinese")
        user_prompt = summary.to_text()
        raw = self._call_api(system_prompt, user_prompt, self.translate_model)
        return parse_chinese_markdown(raw)

    def _call_api(self, system_prompt: str, user_prompt: str, model: str) -> str:
        """Call Anthropic messages API and return response text."""
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=4096,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            raise AnthropicAPIError(f"Anthropic API call failed: {e}") from e
