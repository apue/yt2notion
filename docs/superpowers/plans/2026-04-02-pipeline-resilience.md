# Pipeline Resilience Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `yt2notion process <url>` reliably run to completion without human interaction, with retry on transient failures and structured failure reporting.

**Architecture:** Add a shared `retry()` helper used by all `claude -p` callers and the remote ASR transcriber. Remove interactive confirmation. Add failure tracking to workspace. Fix deferred review to not silently degrade.

**Tech Stack:** Python 3.11+, subprocess, httpx, pytest

**Spec:** `docs/superpowers/specs/2026-04-01-pipeline-resilience-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `src/yt2notion/retry.py` | Create | Retry helper with exponential backoff |
| `src/yt2notion/models/llm.py` | Modify | Add retry + timeout to `ClaudeCodeCaller.call()` |
| `src/yt2notion/models/claude_code.py` | Modify | Add retry + timeout to `ClaudeCodeModel._call_claude()` |
| `src/yt2notion/transcribe/remote.py` | Modify | Add retry to `RemoteTranscriber.transcribe()` |
| `src/yt2notion/pipeline.py` | Modify | Remove confirm; add failure tracking; fix deferred review |
| `src/yt2notion/workspace.py` | Modify | Add `save_failure()` / `clear_failure()` |
| `tests/test_retry.py` | Create | Tests for retry helper |
| `tests/test_llm_retry.py` | Create | Tests for ClaudeCodeCaller + ClaudeCodeModel retry |
| `tests/test_transcriber_retry.py` | Create | Tests for RemoteTranscriber retry |
| `tests/test_workspace.py` | Modify | Tests for failure tracking methods |
| `tests/test_pipeline.py` | Modify | Remove `no_confirm`; test failure tracking |

---

### Task 1: Retry Helper

**Files:**
- Create: `src/yt2notion/retry.py`
- Create: `tests/test_retry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_retry.py
"""Tests for retry helper."""

from __future__ import annotations

import pytest

from yt2notion.retry import retry, RetryExhausted


def test_retry_succeeds_first_try():
    calls = []

    def fn():
        calls.append(1)
        return "ok"

    result = retry(fn, max_retries=3, base_delay=0.0)
    assert result == "ok"
    assert len(calls) == 1


def test_retry_succeeds_after_failures():
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 3:
            raise ValueError("transient")
        return "ok"

    result = retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert result == "ok"
    assert len(calls) == 3


def test_retry_exhausted():
    def fn():
        raise ValueError("always fails")

    with pytest.raises(RetryExhausted) as exc_info:
        retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert exc_info.value.attempts == 3
    assert isinstance(exc_info.value.__cause__, ValueError)


def test_retry_non_retryable_raises_immediately():
    calls = []

    def fn():
        calls.append(1)
        raise TypeError("not retryable")

    with pytest.raises(TypeError):
        retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,))
    assert len(calls) == 1


def test_retry_logs_to_stderr(capsys):
    calls = []

    def fn():
        calls.append(1)
        if len(calls) < 2:
            raise ValueError("oops")
        return "ok"

    retry(fn, max_retries=3, base_delay=0.0, retryable=(ValueError,), label="test-call")
    captured = capsys.readouterr()
    assert "Retry 1/3" in captured.err
    assert "test-call" in captured.err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_retry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'yt2notion.retry'`

- [ ] **Step 3: Implement retry helper**

```python
# src/yt2notion/retry.py
"""Retry helper with exponential backoff for transient failures."""

from __future__ import annotations

import sys
import time
from typing import Callable, TypeVar

T = TypeVar("T")


class RetryExhausted(Exception):
    """All retry attempts failed."""

    def __init__(self, attempts: int, last_error: Exception) -> None:
        self.attempts = attempts
        super().__init__(f"Failed after {attempts} attempts: {last_error}")
        self.__cause__ = last_error


def retry(
    fn: Callable[[], T],
    *,
    max_retries: int = 3,
    base_delay: float = 5.0,
    retryable: tuple[type[Exception], ...] = (Exception,),
    label: str = "",
) -> T:
    """Call fn(), retrying on retryable exceptions with exponential backoff.

    Args:
        fn: Zero-argument callable to invoke.
        max_retries: Maximum number of attempts.
        base_delay: Base delay in seconds (multiplied by 3^attempt).
        retryable: Tuple of exception types that trigger a retry.
        label: Label for log messages (e.g. "claude -p haiku").

    Returns:
        The return value of fn() on success.

    Raises:
        RetryExhausted: If all attempts fail with a retryable error.
        Exception: If fn() raises a non-retryable error (immediately).
    """
    last_error: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            return fn()
        except retryable as e:
            last_error = e
            if attempt < max_retries:
                delay = base_delay * (3 ** (attempt - 1))
                desc = label or "call"
                print(
                    f"Retry {attempt}/{max_retries} for {desc} "
                    f"(error: {e!s:.100}), waiting {delay:.0f}s...",
                    file=sys.stderr,
                )
                time.sleep(delay)
    raise RetryExhausted(max_retries, last_error)  # type: ignore[arg-type]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_retry.py -v`
Expected: 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/retry.py tests/test_retry.py
git commit -m "feat: add retry helper with exponential backoff"
```

---

### Task 2: Add Retry to ClaudeCodeCaller

**Files:**
- Modify: `src/yt2notion/models/llm.py:28-50`
- Create: `tests/test_llm_retry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_llm_retry.py
"""Tests for retry behavior in ClaudeCodeCaller and ClaudeCodeModel."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from yt2notion.models.llm import ClaudeCodeCaller
from yt2notion.retry import RetryExhausted


@patch("subprocess.run")
def test_caller_retries_on_called_process_error(mock_run):
    """ClaudeCodeCaller retries on non-zero exit code."""
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "claude", stderr="rate limited"),
        subprocess.CompletedProcess(
            "claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""
        ),
    ]
    caller = ClaudeCodeCaller(model="haiku")
    result = caller.call("system", "user", max_tokens=100)
    assert result == "ok"
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_caller_retries_on_empty_output(mock_run):
    """ClaudeCodeCaller retries when output is empty."""
    mock_run.side_effect = [
        subprocess.CompletedProcess("claude", 0, stdout="", stderr=""),
        subprocess.CompletedProcess(
            "claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""
        ),
    ]
    caller = ClaudeCodeCaller(model="haiku")
    result = caller.call("system", "user", max_tokens=100)
    assert result == "ok"
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_caller_retries_on_timeout(mock_run):
    """ClaudeCodeCaller retries on subprocess timeout."""
    mock_run.side_effect = [
        subprocess.TimeoutExpired("claude", 120),
        subprocess.CompletedProcess(
            "claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""
        ),
    ]
    caller = ClaudeCodeCaller(model="haiku")
    result = caller.call("system", "user", max_tokens=100)
    assert result == "ok"
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_caller_no_retry_on_file_not_found(mock_run):
    """ClaudeCodeCaller does NOT retry when claude binary is missing."""
    mock_run.side_effect = FileNotFoundError("claude not found")
    caller = ClaudeCodeCaller(model="haiku")
    with pytest.raises(RuntimeError, match="not found"):
        caller.call("system", "user")
    assert mock_run.call_count == 1


@patch("subprocess.run")
def test_caller_exhausts_retries(mock_run):
    """ClaudeCodeCaller raises RetryExhausted after max retries."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "claude", stderr="error")
    caller = ClaudeCodeCaller(model="haiku")
    with pytest.raises(RetryExhausted):
        caller.call("system", "user")
    assert mock_run.call_count == 3


@patch("subprocess.run")
def test_caller_has_timeout(mock_run):
    """subprocess.run is called with timeout parameter."""
    mock_run.return_value = subprocess.CompletedProcess(
        "claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""
    )
    caller = ClaudeCodeCaller(model="haiku")
    caller.call("system", "user")
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("timeout") == 120
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_llm_retry.py -v`
Expected: FAIL (no retry logic yet, tests expecting retry behavior)

- [ ] **Step 3: Add retry to ClaudeCodeCaller.call()**

Replace the `call()` method in `src/yt2notion/models/llm.py:28-50` with:

```python
    def call(self, system_prompt: str, user_prompt: str, *, max_tokens: int = 4000) -> str:
        prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
        cmd = [
            "claude",
            "-p",
            "--model",
            self.model,
            "--max-turns",
            "1",
            "--output-format",
            "json",
        ]

        from yt2notion.retry import RetryExhausted, retry

        class _EmptyOutputError(Exception):
            pass

        def _run() -> str:
            try:
                result = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True, check=True, timeout=120
                )
            except FileNotFoundError:
                raise RuntimeError("'claude' CLI not found on PATH") from None
            raw = result.stdout
            if not raw or not raw.strip():
                raise _EmptyOutputError("claude returned empty output")
            try:
                output = json.loads(raw)
                return output.get("result", raw)
            except json.JSONDecodeError:
                return raw

        try:
            return retry(
                _run,
                max_retries=3,
                base_delay=5.0,
                retryable=(subprocess.CalledProcessError, subprocess.TimeoutExpired, _EmptyOutputError),
                label=f"claude -p {self.model}",
            )
        except RetryExhausted:
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_llm_retry.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: Run existing tests to check for regressions**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add src/yt2notion/models/llm.py tests/test_llm_retry.py
git commit -m "feat: add retry with exponential backoff to ClaudeCodeCaller"
```

---

### Task 3: Add Retry to ClaudeCodeModel

**Files:**
- Modify: `src/yt2notion/models/claude_code.py:117-151`
- Modify: `tests/test_llm_retry.py` (append tests)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_llm_retry.py`:

```python
from yt2notion.models.claude_code import ClaudeCodeError, ClaudeCodeModel
from yt2notion.models.base import VideoMeta


@pytest.fixture
def mock_meta():
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
        upload_date="20260319",
        duration_seconds=600,
        subtitles_available=True,
    )


SAMPLE_SUMMARY_JSON = json.dumps({
    "sections": [
        {"title": "Intro", "timestamp": "0:00", "timestamp_seconds": 0, "summary": "Introduction"},
    ],
    "overall_summary": "Test summary",
    "suggested_tags": ["test"],
})


@patch("subprocess.run")
def test_claude_code_model_retries_on_error(mock_run, mock_meta):
    """ClaudeCodeModel._call_claude retries on CalledProcessError."""
    mock_run.side_effect = [
        subprocess.CalledProcessError(1, "claude", stderr="overloaded"),
        subprocess.CompletedProcess(
            "claude", 0, stdout=json.dumps({"result": SAMPLE_SUMMARY_JSON}), stderr=""
        ),
    ]
    model = ClaudeCodeModel()
    result = model.summarize("transcript text", mock_meta)
    assert result.overall_summary == "Test summary"
    assert mock_run.call_count == 2


@patch("subprocess.run")
def test_claude_code_model_has_timeout(mock_run, mock_meta):
    """ClaudeCodeModel._call_claude passes timeout to subprocess.run."""
    mock_run.return_value = subprocess.CompletedProcess(
        "claude", 0, stdout=json.dumps({"result": SAMPLE_SUMMARY_JSON}), stderr=""
    )
    model = ClaudeCodeModel()
    model.summarize("transcript text", mock_meta)
    call_kwargs = mock_run.call_args
    assert call_kwargs.kwargs.get("timeout") == 120


@patch("subprocess.run")
def test_claude_code_model_exhausts_retries(mock_run, mock_meta):
    """ClaudeCodeModel._call_claude raises RetryExhausted after max retries."""
    mock_run.side_effect = subprocess.CalledProcessError(1, "claude", stderr="error")
    model = ClaudeCodeModel()
    with pytest.raises(RetryExhausted):
        model.summarize("transcript text", mock_meta)
    assert mock_run.call_count == 3
```

- [ ] **Step 2: Run new tests to verify they fail**

Run: `uv run pytest tests/test_llm_retry.py::test_claude_code_model_retries_on_error tests/test_llm_retry.py::test_claude_code_model_has_timeout tests/test_llm_retry.py::test_claude_code_model_exhausts_retries -v`
Expected: FAIL (no retry in `_call_claude` yet)

- [ ] **Step 3: Add retry to ClaudeCodeModel._call_claude()**

Replace `_call_claude` method in `src/yt2notion/models/claude_code.py:117-151` with:

```python
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

        from yt2notion.retry import RetryExhausted, retry

        class _EmptyOutputError(Exception):
            pass

        def _run() -> str:
            try:
                result = subprocess.run(
                    cmd, input=prompt, capture_output=True, text=True, check=True, timeout=120
                )
            except FileNotFoundError as e:
                raise ClaudeCodeError(
                    "claude CLI not found. Install Claude Code: https://code.claude.com"
                ) from e
            raw = result.stdout
            if not raw or not raw.strip():
                raise _EmptyOutputError("claude returned empty output")
            try:
                output = json.loads(raw)
                return output.get("result", raw)
            except json.JSONDecodeError:
                return raw

        try:
            return retry(
                _run,
                max_retries=3,
                base_delay=5.0,
                retryable=(subprocess.CalledProcessError, subprocess.TimeoutExpired, _EmptyOutputError),
                label=f"claude -p {model}",
            )
        except RetryExhausted:
            raise
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest tests/test_llm_retry.py tests/test_claude_code.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/models/claude_code.py tests/test_llm_retry.py
git commit -m "feat: add retry with exponential backoff to ClaudeCodeModel"
```

---

### Task 4: Add Retry to RemoteTranscriber

**Files:**
- Modify: `src/yt2notion/transcribe/remote.py:23-54`
- Create: `tests/test_transcriber_retry.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_transcriber_retry.py
"""Tests for retry behavior in RemoteTranscriber."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import httpx
import pytest

from yt2notion.retry import RetryExhausted
from yt2notion.transcribe.remote import RemoteTranscriber, TranscriptionError


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "test.mp3"
    p.write_bytes(b"fake audio data")
    return p


def _ok_response():
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 200
    resp.json.return_value = {
        "segments": [{"start": 0.0, "end": 5.0, "text": "Hello world"}]
    }
    resp.raise_for_status = MagicMock()
    return resp


def _server_error_response():
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 503
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503 Service Unavailable", request=MagicMock(), response=resp
    )
    return resp


@patch("httpx.post")
def test_transcriber_retries_on_connect_error(mock_post, audio_file):
    mock_post.side_effect = [
        httpx.ConnectError("Connection refused"),
        _ok_response(),
    ]
    t = RemoteTranscriber(endpoint="http://localhost:8000")
    result = t.transcribe(audio_file)
    assert len(result) == 1
    assert result[0].text == "Hello world"
    assert mock_post.call_count == 2


@patch("httpx.post")
def test_transcriber_retries_on_timeout(mock_post, audio_file):
    mock_post.side_effect = [
        httpx.TimeoutException("read timed out"),
        _ok_response(),
    ]
    t = RemoteTranscriber(endpoint="http://localhost:8000")
    result = t.transcribe(audio_file)
    assert len(result) == 1
    assert mock_post.call_count == 2


@patch("httpx.post")
def test_transcriber_retries_on_5xx(mock_post, audio_file):
    mock_post.side_effect = [
        _server_error_response(),
        _ok_response(),
    ]
    t = RemoteTranscriber(endpoint="http://localhost:8000")
    result = t.transcribe(audio_file)
    assert len(result) == 1
    assert mock_post.call_count == 2


@patch("httpx.post")
def test_transcriber_no_retry_on_4xx(mock_post, audio_file):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = 400
    resp.raise_for_status.side_effect = httpx.HTTPStatusError(
        "400 Bad Request", request=MagicMock(), response=resp
    )
    mock_post.return_value = resp
    t = RemoteTranscriber(endpoint="http://localhost:8000")
    with pytest.raises(TranscriptionError, match="ASR request failed"):
        t.transcribe(audio_file)
    assert mock_post.call_count == 1


@patch("httpx.post")
def test_transcriber_exhausts_retries(mock_post, audio_file):
    mock_post.side_effect = httpx.ConnectError("Connection refused")
    t = RemoteTranscriber(endpoint="http://localhost:8000")
    with pytest.raises(TranscriptionError, match="ASR request failed"):
        t.transcribe(audio_file)
    assert mock_post.call_count == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transcriber_retry.py -v`
Expected: FAIL (no retry logic in transcriber yet)

- [ ] **Step 3: Add retry to RemoteTranscriber.transcribe()**

Replace the `transcribe` method in `src/yt2notion/transcribe/remote.py:23-54` with:

```python
    def transcribe(self, audio_path: Path, *, language: str | None = None) -> list[SubtitleEntry]:
        """Send audio to remote ASR service, return SubtitleEntry list."""
        url = f"{self.endpoint}/transcribe"
        data: dict[str, str] = {}
        if language:
            data["language"] = language

        from yt2notion.retry import RetryExhausted, retry

        class _RetryableHTTPError(Exception):
            """Wrapper for HTTP errors that should trigger retry."""

        def _post() -> httpx.Response:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, "audio/mpeg")}
                response = httpx.post(
                    url,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                if response.status_code >= 500:
                    raise _RetryableHTTPError(str(e)) from e
                raise TranscriptionError(f"ASR request failed: {e}") from e
            return response

        try:
            response = retry(
                _post,
                max_retries=3,
                base_delay=10.0,
                retryable=(httpx.ConnectError, httpx.TimeoutException, _RetryableHTTPError),
                label="ASR transcribe",
            )
        except RetryExhausted as e:
            raise TranscriptionError(f"ASR request failed after retries: {e}") from e

        result = response.json()
        segments = result.get("segments", [])

        return [
            SubtitleEntry(
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                text=seg["text"].strip(),
            )
            for seg in segments
            if seg.get("text", "").strip()
        ]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transcriber_retry.py tests/test_transcribe.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/transcribe/remote.py tests/test_transcriber_retry.py
git commit -m "feat: add retry with exponential backoff to RemoteTranscriber"
```

---

### Task 5: Workspace Failure Tracking

**Files:**
- Modify: `src/yt2notion/workspace.py`
- Modify: `tests/test_workspace.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_workspace.py`:

```python
def test_save_failure(ws):
    ws.save_failure(url="https://example.com", step="review", error="timeout")
    failed = ws._read_json("failed.json")
    assert failed["url"] == "https://example.com"
    assert failed["step"] == "review"
    assert failed["error"] == "timeout"
    assert failed["retries_exhausted"] is True
    assert "timestamp" in failed


def test_clear_failure(ws):
    ws.save_failure(url="https://example.com", step="review", error="timeout")
    assert (ws.dir / "failed.json").exists()
    ws.clear_failure()
    assert not (ws.dir / "failed.json").exists()


def test_clear_failure_noop_when_missing(ws):
    """clear_failure should not error when failed.json doesn't exist."""
    ws.clear_failure()  # Should not raise
```

Note: these tests assume the existing `ws` fixture in `tests/test_workspace.py` provides a `Workspace` instance. Check that this fixture exists — if not, the fixture is:

```python
@pytest.fixture
def ws(tmp_path):
    from yt2notion.workspace import Workspace
    return Workspace(tmp_path, "test_video")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workspace.py::test_save_failure tests/test_workspace.py::test_clear_failure tests/test_workspace.py::test_clear_failure_noop_when_missing -v`
Expected: FAIL with `AttributeError: 'Workspace' object has no attribute 'save_failure'`

- [ ] **Step 3: Add save_failure and clear_failure to Workspace**

Add after the `save_summary` method in `src/yt2notion/workspace.py` (before `# --- Internal helpers ---`):

```python
    # --- Failure tracking ---

    def save_failure(self, *, url: str, step: str, error: str) -> None:
        """Write a structured failure record."""
        from datetime import datetime, timezone

        self._write_json("failed.json", {
            "url": url,
            "step": step,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "retries_exhausted": True,
        })

    def clear_failure(self) -> None:
        """Remove failed.json if it exists (called on success)."""
        path = self.dir / "failed.json"
        if path.exists():
            path.unlink()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_workspace.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/workspace.py tests/test_workspace.py
git commit -m "feat: add failure tracking to Workspace (save_failure/clear_failure)"
```

---

### Task 6: Remove Interactive Confirmation & Add Failure Tracking to Pipeline

**Files:**
- Modify: `src/yt2notion/pipeline.py:31-41` (signature), `171-179` (confirm block), `194-207` (end)
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Update pipeline tests**

In `tests/test_pipeline.py`, make these changes:

1. Remove `no_confirm=True` from `test_pipeline_full_mock` (line 102) — it should work without it now.

2. Add a new test for failure tracking:

```python
@patch("yt2notion.pipeline.create_llm_caller")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_pipeline_writes_failed_json_on_error(
    mock_extract_meta,
    mock_extract_subs,
    mock_create_summarizer,
    mock_create_llm_caller,
    mock_meta,
    config,
    tmp_path,
):
    mock_extract_meta.return_value = mock_meta

    srt_file = tmp_path / "abc123.en.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:05,000\nHello world\n")
    mock_extract_subs.return_value = srt_file

    # Make entity extraction fail
    mock_caller = MagicMock()
    mock_caller.call.side_effect = RuntimeError("LLM exploded")
    mock_create_llm_caller.return_value = mock_caller

    mock_summarizer = MagicMock()
    mock_create_summarizer.return_value = mock_summarizer

    from yt2notion.pipeline import run_pipeline

    with pytest.raises(RuntimeError, match="LLM exploded"):
        run_pipeline("https://www.youtube.com/watch?v=abc123", config)

    # Check that failed.json was written
    from pathlib import Path

    ws_dir = Path(config.workspace["base_dir"]) / "abc123"
    failed = json.loads((ws_dir / "failed.json").read_text())
    assert failed["step"] == "extract"
    assert "LLM exploded" in failed["error"]
```

Add `import json` at the top of the test file if not already present.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py::test_pipeline_writes_failed_json_on_error -v`
Expected: FAIL

- [ ] **Step 3: Modify pipeline.py**

Three changes to `src/yt2notion/pipeline.py`:

**3a. Remove `no_confirm` parameter from `run_pipeline` signature (line 37):**

Remove the line:
```python
    no_confirm: bool = False,
```

**3b. Remove the confirm block (lines 171-179):**

Delete this entire block:
```python
    if not no_confirm:
        typer.echo("\n--- Preview ---")
        typer.echo(chinese_content.raw_markdown[:500])
        if len(chinese_content.raw_markdown) > 500:
            typer.echo("...(truncated)")
        typer.echo("--- End Preview ---\n")
        if not typer.confirm("Publish to storage?"):
            typer.echo("Aborted.")
            return ""
```

**3c. Add failure tracking by wrapping the pipeline body.**

After the workspace (`ws`) is created/loaded (around line 100 after metadata is loaded), add a try/except around all remaining steps. The structure:

```python
    # After ws is created and metadata is loaded...
    current_step = "segment"
    try:
        # --- Step 2: SEGMENT ---
        current_step = "segment"
        # ... existing segment code ...

        current_step = "transcribe"
        # ... existing transcribe code ...

        current_step = "review"
        # ... existing review code ...

        current_step = "extract"
        # ... existing extract code ...

        current_step = "summarize"
        # ... existing summarize code ...

        # ... publish code ...

        current_step = "publish"
        # ... deferred review code ...

        ws.clear_failure()
        return result_url

    except Exception as e:
        if ws is not None:
            ws.save_failure(url=url, step=current_step, error=str(e))
        raise
```

Note: the `dry_run` return path should be **inside** the try block (before publish). The `ws.clear_failure()` call goes right before the final `return result_url`.

The except block re-raises so the CLI layer still gets the exception for exit code handling.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: All PASS

- [ ] **Step 5: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add src/yt2notion/pipeline.py tests/test_pipeline.py
git commit -m "feat: remove interactive confirm, add failure tracking to pipeline"
```

---

### Task 7: Fix Deferred Review Error Handling

**Files:**
- Modify: `src/yt2notion/pipeline.py:672-725` (the `_step_deferred_review` function)

- [ ] **Step 1: Modify deferred review error handling**

In `src/yt2notion/pipeline.py`, replace the try/except block in `_step_deferred_review` (currently lines 706-718):

Current code:
```python
    try:
        for i, group in enumerate(groups):
            if verbose:
                typer.echo(f"  Review [{i + 1}/{len(groups)}] {group.get('title', '')}")
            cleaned = review_segment(group["text"], metadata, config, review_context)
            reviewed_groups.append(cleaned)

        # Split reviewed text back to original segment granularity
        reviewed = _redistribute_reviewed_text(transcripts, groups, reviewed_groups)
        ws.save_reviewed(reviewed)
    except Exception as e:
        typer.echo(f"  Warning: review failed ({e}), using unreviewed transcript")
        reviewed = transcripts
```

Replace with:
```python
    from yt2notion.retry import RetryExhausted

    try:
        for i, group in enumerate(groups):
            if verbose:
                typer.echo(f"  Review [{i + 1}/{len(groups)}] {group.get('title', '')}")
            cleaned = review_segment(group["text"], metadata, config, review_context)
            reviewed_groups.append(cleaned)

        # Split reviewed text back to original segment granularity
        reviewed = _redistribute_reviewed_text(transcripts, groups, reviewed_groups)
        ws.save_reviewed(reviewed)
    except (RetryExhausted, RuntimeError) as e:
        typer.echo(
            f"  Warning: deferred review failed ({e}), using unreviewed transcript",
            err=True,
        )
        reviewed = transcripts
        # Mark first segment so storage can show degradation notice
        reviewed = [dict(seg) for seg in reviewed]  # shallow copy
        reviewed[0]["_unreviewed"] = True
```

- [ ] **Step 2: Add degradation notice to Obsidian storage**

In `src/yt2notion/storage/obsidian.py`, find the `_render_transcript` method (or wherever transcript segments are rendered). Add at the start of the transcript output, before iterating segments:

Check if any segment has `_unreviewed` flag, and if so prepend:
```python
        if any(seg.get("_unreviewed") for seg in transcript_segments):
            lines.append("> ⚠️ 逐字稿未经校对（校对步骤失败）\n")
```

Also apply the same to `src/yt2notion/storage/notion.py` in `_create_transcript_page`:

Add before the segment loop:
```python
        if any(seg.get("_unreviewed") for seg in transcript_segments):
            blocks.append({
                "callout": {
                    "icon": {"emoji": "⚠️"},
                    "rich_text": [{"text": {"content": "逐字稿未经校对（校对步骤失败）"}}],
                    "color": "yellow_background",
                }
            })
```

- [ ] **Step 3: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 4: Commit**

```bash
git add src/yt2notion/pipeline.py src/yt2notion/storage/obsidian.py src/yt2notion/storage/notion.py
git commit -m "fix: deferred review uses targeted catch, adds degradation notice"
```

---

### Task 8: Clean Up CLI (remove no_confirm passthrough)

**Files:**
- Modify: `src/yt2notion/cli.py:19,41`
- Modify: `tests/test_cli.py`

- [ ] **Step 1: Remove no_confirm from CLI**

In `src/yt2notion/cli.py`:

1. Remove line 19: `no_confirm: bool = typer.Option(False, "--no-confirm", help="Skip confirmation prompt"),`
2. Remove `no_confirm=no_confirm,` from the `run_pipeline` call (line 41)

Keep `--no-confirm` as a hidden no-op option if backwards compatibility matters, or just remove it. Since the spec says "can stay for backwards compatibility", keep it but don't pass it:

Replace line 19 with:
```python
    no_confirm: bool = typer.Option(False, "--no-confirm", hidden=True, help="Deprecated (now default)"),
```

And remove `no_confirm=no_confirm,` from the `run_pipeline` call.

- [ ] **Step 2: Update CLI tests**

In `tests/test_cli.py`, update `test_cli_process_invocation`:

Remove the assertion about `no_confirm`:
```python
    assert call_kwargs.kwargs.get("no_confirm") is True
```

The test should still pass `--no-confirm` on the command line (backwards compat), but the pipeline shouldn't receive it.

- [ ] **Step 3: Run tests**

Run: `uv run pytest tests/test_cli.py tests/test_pipeline.py -v`
Expected: All PASS

- [ ] **Step 4: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/cli.py tests/test_cli.py
git commit -m "chore: deprecate --no-confirm flag (publish is now non-interactive)"
```

---

### Task 9: Final Verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 2: Run linter**

Run: `uv run ruff check src/ tests/`
Expected: No errors

- [ ] **Step 3: Run formatter**

Run: `uv run ruff format src/ tests/`
Expected: No changes (or auto-format applied)

- [ ] **Step 4: Verify no regressions by checking key flows**

Manually verify these assertions about the final state:
1. `grep -r "typer.confirm" src/` returns no results
2. `grep -r "no_confirm" src/yt2notion/pipeline.py` returns no results
3. `grep -r "class RetryExhausted" src/` returns exactly 1 result in `retry.py`
4. `grep -r "retry(" src/yt2notion/models/llm.py src/yt2notion/models/claude_code.py src/yt2notion/transcribe/remote.py` returns 3 results (one per file)

- [ ] **Step 5: Commit any final fixes**

```bash
# Only if needed
git add -A
git commit -m "fix: final cleanup for pipeline resilience"
```
