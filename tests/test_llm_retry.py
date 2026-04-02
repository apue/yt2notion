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
        subprocess.CompletedProcess("claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""),
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
        subprocess.CompletedProcess("claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""),
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
        subprocess.CompletedProcess("claude", 0, stdout=json.dumps({"result": "ok"}), stderr=""),
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
