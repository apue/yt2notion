"""Codex CLI backend using `codex exec` in non-interactive mode."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from yt2notion.retry import RetryExhaustedError, retry


class CodexCLIError(Exception):
    """Raised when codex CLI invocation fails."""


_CLAUDE_ALIASES = {"sonnet", "opus", "haiku"}


def _normalize_codex_model(model: str, *, fallback: str = "gpt-5.4") -> str:
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


def _normalize_profile(profile: str | None) -> str | None:
    raw = (profile or "").strip()
    return raw or None


class _EmptyOutputError(Exception):
    """Raised when codex returns no usable output."""


def _run_codex_exec(
    prompt: str,
    *,
    model: str,
    timeout_seconds: int,
    reasoning_effort: str,
    profile: str | None = None,
    workdir: str | None = None,
) -> str:
    """Run `codex exec` and return the final assistant message."""
    with tempfile.NamedTemporaryFile(prefix="yt2notion-codex-", suffix=".txt", delete=False) as f:
        output_path = Path(f.name)

    cmd = [
        "codex",
        "exec",
    ]
    if profile:
        cmd.extend(["-p", profile])
    cmd.extend(
        [
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
    )
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
        model: str = "gpt-5.4",
        *,
        timeout_seconds: int = 300,
        max_attempts: int = 1,
        reasoning_effort: str = "low",
        profile: str | None = None,
        workdir: str | None = None,
    ) -> None:
        self.model = _normalize_codex_model(model)
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max_attempts
        self.reasoning_effort = _normalize_reasoning_effort(reasoning_effort)
        self.profile = _normalize_profile(profile)
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
                profile=self.profile,
                workdir=self.workdir,
            )

        try:
            return retry(
                _run,
                max_retries=self.max_attempts,
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
