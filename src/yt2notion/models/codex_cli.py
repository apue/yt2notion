"""Codex CLI backend using `codex exec` in non-interactive mode."""

from __future__ import annotations

import json
import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.models._parsers import (
    parse_chinese_markdown,
    parse_chunk_summary_json,
    parse_note_document_json,
    parse_note_metadata_json,
    parse_review_summary_json,
    parse_summary_json,
    parse_synthesized_markdown,
)
from yt2notion.prompts import load_prompt, render_prompt
from yt2notion.retry import RetryExhaustedError, retry

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


class CodexCLIError(Exception):
    """Raised when codex CLI invocation fails."""


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


_CLAUDE_ALIASES = {"sonnet", "opus", "haiku"}


def _normalize_codex_model(model: str, *, fallback: str = "gpt-5.2") -> str:
    """Map legacy Claude aliases to Codex defaults for smoother backend switching."""
    raw = (model or "").strip()
    if not raw or raw in _CLAUDE_ALIASES:
        return fallback
    return raw


def _normalize_reasoning_effort(reasoning_effort: str, *, fallback: str = "low") -> str:
    """Normalize reasoning effort for Codex CLI config overrides."""
    raw = (reasoning_effort or "").strip().lower()
    if not raw:
        return fallback
    return raw


class _EmptyOutputError(Exception):
    """Raised when codex returns no usable output."""


def _run_codex_exec(
    prompt: str,
    *,
    model: str,
    timeout_seconds: int,
    reasoning_effort: str,
    workdir: str | None = None,
) -> str:
    """Run `codex exec` and return the final assistant message."""
    with tempfile.NamedTemporaryFile(prefix="yt2notion-codex-", suffix=".txt", delete=False) as f:
        output_path = Path(f.name)

    cmd = [
        "codex",
        "exec",
        "-m",
        model,
        "-c",
        f'model_reasoning_effort="{reasoning_effort}"',
        "--sandbox",
        "read-only",
        "--output-last-message",
        str(output_path),
        "-",
    ]
    if workdir is not None:
        cmd.insert(-1, "--skip-git-repo-check")

    try:
        try:
            subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
                cwd=workdir,
            )
        except FileNotFoundError as e:
            if workdir is not None and e.filename == workdir:
                raise CodexCLIError(f"codex working directory not found: {workdir}") from e
            raise CodexCLIError("'codex' CLI not found on PATH") from e

        try:
            raw = output_path.read_text(encoding="utf-8")
        except FileNotFoundError:
            raw = ""
    finally:
        output_path.unlink(missing_ok=True)

    text = raw.strip()
    if not text:
        raise _EmptyOutputError("codex returned empty output")
    return text


class CodexCLICaller:
    """One-shot LLM caller using `codex exec`."""

    def __init__(
        self,
        model: str = "gpt-5.2",
        *,
        timeout_seconds: int = 300,
        reasoning_effort: str = "low",
        workdir: str | None = None,
    ) -> None:
        self.model = _normalize_codex_model(model)
        self.timeout_seconds = timeout_seconds
        self.reasoning_effort = _normalize_reasoning_effort(reasoning_effort)
        self.workdir = workdir

    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        # max_tokens is part of the shared protocol; codex CLI does not expose a direct equivalent.
        del max_tokens
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"

        def _run() -> str:
            return _run_codex_exec(
                prompt,
                model=self.model,
                timeout_seconds=self.timeout_seconds,
                reasoning_effort=self.reasoning_effort,
                workdir=self.workdir,
            )

        try:
            return retry(
                _run,
                max_retries=3,
                base_delay=5.0,
                retryable=(
                    subprocess.CalledProcessError,
                    subprocess.TimeoutExpired,
                    _EmptyOutputError,
                ),
                label=f"codex exec {self.model}",
            )
        except RetryExhaustedError:
            raise


class CodexCLIModel:
    """Summarizer backend using `codex exec`."""

    def __init__(
        self,
        summarize_model: str = "gpt-5.2",
        translate_model: str = "gpt-5.2",
        *,
        reasoning_effort: str = "low",
        workdir: str | None = None,
    ) -> None:
        self.summarize_model = _normalize_codex_model(summarize_model)
        self.translate_model = _normalize_codex_model(translate_model)
        self.reasoning_effort = _normalize_reasoning_effort(reasoning_effort)
        self.workdir = workdir
        self._summarize_caller = CodexCLICaller(
            self.summarize_model,
            reasoning_effort=self.reasoning_effort,
            workdir=self.workdir,
        )
        self._translate_caller = CodexCLICaller(
            self.translate_model,
            reasoning_effort=self.reasoning_effort,
            workdir=self.workdir,
        )

    def summarize(
        self, transcript: str, metadata: VideoMeta, *, prompt_name: str = "summarize"
    ) -> Summary:
        """Produce a structured summary with timestamps."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\nURL: {metadata.url}\n\n{transcript}"
        )
        raw = self._summarize_caller.call(system_prompt, user_prompt)
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
        raw = self._summarize_caller.call(system_prompt, user_prompt)
        return parse_review_summary_json(raw)

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        del metadata
        system_prompt = load_prompt("chinese")
        raw = self._translate_caller.call(system_prompt, summary.to_text())
        return parse_chinese_markdown(raw)

    def summarize_chunk(
        self, chunk_transcript: str, metadata: VideoMeta, segment_info: dict
    ) -> ChunkSummary:
        """Map phase: summarize a single segment of long content."""
        system_prompt = render_prompt("summarize_chunk", **segment_info)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\n"
            f"URL: {metadata.url}\n\n{chunk_transcript}"
        )
        raw = self._summarize_caller.call(system_prompt, user_prompt)
        return parse_chunk_summary_json(raw)

    def synthesize(
        self,
        chunk_summaries: list[ChunkSummary],
        metadata: VideoMeta,
        *,
        prompt_name: str = "synthesize",
    ) -> ChineseContent:
        """Reduce phase: synthesize all chunk summaries into final Chinese output."""
        from yt2notion.process import seconds_to_display

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
        raw = self._translate_caller.call(system_prompt, user_prompt)
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
        raw = self._translate_caller.call(system_prompt, user_prompt)
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
        raw = self._translate_caller.call(system_prompt, user_prompt)
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
        raw = self._translate_caller.call(system_prompt, user_prompt)
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
        raw = self._translate_caller.call(system_prompt, user_prompt)
        return parse_note_metadata_json(raw)
