"""Claude Code (-p mode) LLM backend. Uses CC subscription, zero API cost."""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING

from yt2notion.models._parsers import parse_chinese_markdown, parse_summary_json
from yt2notion.prompts import load_prompt

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, Summary, VideoMeta


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
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                check=True,
            )
        except FileNotFoundError as e:
            raise ClaudeCodeError(
                "claude CLI not found. Install Claude Code: https://code.claude.com"
            ) from e
        except subprocess.CalledProcessError as e:
            raise ClaudeCodeError(f"claude CLI failed: {e.stderr.strip()}") from e

        # Parse JSON output — result is in the "result" field
        try:
            output = json.loads(result.stdout)
            return output.get("result", result.stdout)
        except json.JSONDecodeError:
            # Fallback: treat stdout as raw text
            return result.stdout
