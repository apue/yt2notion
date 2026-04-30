"""Claude Code (-p mode) LLM backend. Uses CC subscription, zero API cost."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from yt2notion.models._parsers import (
    parse_note_document_json,
    parse_note_metadata_json,
)
from yt2notion.prompts import load_prompt
from yt2notion.retry import retry

if TYPE_CHECKING:
    from yt2notion.models.base import (
        NoteDocument,
        NoteMetadata,
        VideoMeta,
    )


class ClaudeCodeError(Exception):
    """Raised when claude CLI invocation fails."""


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


class ClaudeCodeModel:
    """LLM backend using `claude -p` (Claude Code CLI)."""

    def __init__(
        self,
        summarize_model: str = "sonnet",
        translate_model: str = "opus",
    ) -> None:
        self.summarize_model = summarize_model
        self.translate_model = translate_model

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
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.translate_model,
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
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.translate_model,
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
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.translate_model,
        )
        return parse_note_metadata_json(raw)

    def _call_claude(self, system_prompt: str, user_prompt: str, model: str) -> str:
        """Call claude CLI and return the result text."""
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        cmd = [
            "claude",
            "-p",
            "--model",
            model,
            "--max-turns",
            "1",
            "--output-format",
            "json",
        ]

        class _EmptyOutputError(Exception):
            """Raised when claude returns empty output."""

        def _run() -> str:
            try:
                result = subprocess.run(
                    cmd,
                    input=prompt,
                    capture_output=True,
                    text=True,
                    check=True,
                    timeout=120,
                )
            except FileNotFoundError as e:
                raise ClaudeCodeError(
                    "claude CLI not found. Install Claude Code: https://code.claude.com"
                ) from e

            raw = result.stdout
            if not raw or not raw.strip():
                raise _EmptyOutputError("claude returned empty output")

            # Parse JSON output — result is in the "result" field.
            # If the output is not valid JSON, keep the raw stdout fallback.
            try:
                output = json.loads(raw)
                return output.get("result", raw)
            except json.JSONDecodeError:
                return raw

        return retry(
            _run,
            max_retries=3,
            base_delay=5.0,
            retryable=(
                subprocess.CalledProcessError,
                subprocess.TimeoutExpired,
                _EmptyOutputError,
            ),
            label=f"claude -p {model}",
        )
