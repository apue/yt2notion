"""Claude Code (-p mode) LLM backend. Uses CC subscription, zero API cost."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from yt2notion.models._parsers import (
    parse_chinese_markdown,
    parse_summary_json,
)
from yt2notion.prompts import load_prompt
from yt2notion.retry import retry

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, ChunkSummary, Summary, VideoMeta


class ClaudeCodeError(Exception):
    """Raised when claude CLI invocation fails."""


class ClaudeCodeModel:
    """LLM backend using `claude -p` (Claude Code CLI)."""

    def __init__(
        self,
        summarize_model: str = "sonnet",
        translate_model: str = "opus",
    ) -> None:
        self.summarize_model = summarize_model
        self.translate_model = translate_model

    def summarize(
        self, transcript: str, metadata: VideoMeta, *, prompt_name: str = "summarize"
    ) -> Summary:
        """Produce a structured summary with timestamps."""
        system_prompt = load_prompt(prompt_name)
        user_prompt = (
            f"Video: {metadata.title} by {metadata.channel}\nURL: {metadata.url}\n\n{transcript}"
        )
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.summarize_model,
        )
        return parse_summary_json(raw)

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        system_prompt = load_prompt("chinese")
        user_prompt = summary.to_text()
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.translate_model,
        )
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
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.summarize_model,
        )
        return parse_chunk_summary_json(raw)

    def synthesize(
        self, chunk_summaries: list[ChunkSummary], metadata: VideoMeta
    ) -> ChineseContent:
        """Reduce phase: synthesize all chunk summaries into final Chinese output."""
        from yt2notion.models._parsers import parse_synthesized_markdown
        from yt2notion.process import seconds_to_display
        from yt2notion.prompts import render_prompt

        duration_display = seconds_to_display(metadata.duration_seconds)
        system_prompt = render_prompt(
            "synthesize",
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
        raw = self._call_claude(
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            model=self.translate_model,
        )
        return parse_synthesized_markdown(raw)

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
