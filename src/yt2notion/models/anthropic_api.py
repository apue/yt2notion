"""Anthropic API LLM backend. Requires API key, pay per token."""

from __future__ import annotations

import json
from typing import TYPE_CHECKING

from yt2notion.models._parsers import (
    parse_chinese_markdown,
    parse_note_document_json,
    parse_note_metadata_json,
    parse_review_summary_json,
    parse_summary_json,
)
from yt2notion.prompts import load_prompt

if TYPE_CHECKING:
    from yt2notion.models.base import (
        ChineseContent,
        ChunkSummary,
        NoteDocument,
        NoteMetadata,
        ReviewSummaryResult,
        Summary,
        VideoMeta,
    )

try:
    import anthropic as _anthropic
except ImportError:
    _anthropic = None  # type: ignore[assignment]


class AnthropicAPIError(Exception):
    """Raised when Anthropic API call fails."""


def _source_context(metadata: VideoMeta) -> dict[str, object]:
    """Build compact source context for note composition prompts."""
    return {
        "video_id": metadata.video_id,
        "title": metadata.title,
        "channel": metadata.channel,
        "url": metadata.url,
        "duration_seconds": metadata.duration_seconds,
        "description": metadata.description,
        "series": metadata.series,
    }


def _note_document_payload(note: NoteDocument) -> dict[str, object]:
    """Serialize a note document for prompt input."""
    return {
        "title": note.title,
        "markdown": note.markdown,
        "tags": note.tags,
        "variant": note.variant,
    }


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

    def review_and_summarize(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        prompt_name: str = "summarize_reviewed",
    ) -> ReviewSummaryResult:
        """Review raw ASR transcript and summarize it in one pass."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\nURL: {metadata.url}\n\n{transcript}"
        )
        raw = self._call_api(system_prompt, user_prompt, self.summarize_model)
        return parse_review_summary_json(raw)

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        system_prompt = load_prompt("chinese")
        user_prompt = summary.to_text()
        raw = self._call_api(system_prompt, user_prompt, self.translate_model)
        return parse_chinese_markdown(raw)

    def summarize_chunk(
        self, chunk_transcript: str, metadata: VideoMeta, segment_info: dict
    ) -> ChunkSummary:
        """Map phase: summarize a single segment of long content."""

        from yt2notion.models._parsers import parse_chunk_summary_json
        from yt2notion.prompts import render_prompt

        system_prompt = render_prompt("summarize_chunk", **segment_info)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\n"
            f"URL: {metadata.url}\n\n{chunk_transcript}"
        )
        raw = self._call_api(system_prompt, user_prompt, self.summarize_model)
        return parse_chunk_summary_json(raw)

    def synthesize(
        self,
        chunk_summaries: list[ChunkSummary],
        metadata: VideoMeta,
        *,
        prompt_name: str = "synthesize",
    ) -> ChineseContent:
        """Reduce phase: synthesize all chunk summaries into final Chinese output."""
        import json

        from yt2notion.models._parsers import parse_synthesized_markdown
        from yt2notion.process import seconds_to_display
        from yt2notion.prompts import render_prompt

        duration_display = seconds_to_display(metadata.duration_seconds)
        system_prompt = render_prompt(
            prompt_name,
            title=metadata.title,
            channel=metadata.channel,
            duration=duration_display,
            url=metadata.url,
        )
        user_prompt = json.dumps(
            [
                {
                    "segment_title": cs.segment_title,
                    "timestamp": cs.timestamp,
                    "timestamp_seconds": cs.timestamp_seconds,
                    "summary": cs.summary,
                    "key_points": cs.key_points,
                    "key_terms": cs.key_terms,
                }
                for cs in chunk_summaries
            ],
            ensure_ascii=False,
            indent=2,
        )
        raw = self._call_api(system_prompt, user_prompt, self.translate_model)
        return parse_synthesized_markdown(raw)

    def summarize_transcript_to_markdown(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        prompt_name: str,
    ) -> ChineseContent:
        """Generate final Chinese markdown directly from transcript input."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\nURL: {metadata.url}\n\n{transcript}"
        )
        raw = self._call_api(system_prompt, user_prompt, self.translate_model)
        return parse_chinese_markdown(raw)

    def compose_guide_note(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_guide",
    ) -> NoteDocument:
        """Compose a strict JSON guide note from transcript input."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = json.dumps(
            {
                "source": _source_context(metadata),
                "target_chars": target_chars,
                "transcript": transcript,
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = self._call_api(
            system_prompt,
            user_prompt,
            self.translate_model,
            max_tokens=8192,
        )
        return parse_note_document_json(raw, expected_variant="a_guide")

    def compose_longform_note(
        self,
        transcript: str,
        guide_note: NoteDocument,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_longform",
    ) -> NoteDocument:
        """Compose a strict JSON longform note from guide + transcript input."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = json.dumps(
            {
                "source": _source_context(metadata),
                "guide_note": _note_document_payload(guide_note),
                "target_chars": target_chars,
                "transcript": transcript,
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = self._call_api(
            system_prompt,
            user_prompt,
            self.translate_model,
            max_tokens=8192,
        )
        return parse_note_document_json(raw, expected_variant="b_longform")

    def compose_note_metadata(
        self,
        guide_note: NoteDocument,
        longform_note: NoteDocument,
        metadata: VideoMeta,
        *,
        prompt_name: str = "compose_note_metadata",
    ) -> NoteMetadata:
        """Compose strict note metadata from guide and longform notes."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = json.dumps(
            {
                "source": _source_context(metadata),
                "guide_note": _note_document_payload(guide_note),
                "longform_note": _note_document_payload(longform_note),
            },
            ensure_ascii=False,
            indent=2,
        )
        raw = self._call_api(system_prompt, user_prompt, self.translate_model)
        return parse_note_metadata_json(raw)

    def _call_api(
        self,
        system_prompt: str,
        user_prompt: str,
        model: str,
        *,
        max_tokens: int = 4096,
    ) -> str:
        """Call Anthropic messages API and return response text."""
        try:
            response = self.client.messages.create(
                model=model,
                max_tokens=max_tokens,
                system=system_prompt,
                messages=[{"role": "user", "content": user_prompt}],
            )
            return response.content[0].text
        except Exception as e:
            raise AnthropicAPIError(f"Anthropic API call failed: {e}") from e
