"""Contract tests for bounded CLI LLM execution policy."""

from __future__ import annotations

import subprocess
from unittest.mock import patch

import pytest

from yt2notion.models.llm import ClaudeCodeCaller, ClaudeCodeError, create_llm_caller
from yt2notion.retry import RetryExhaustedError


@patch("yt2notion.models.llm.subprocess.run")
def test_claude_timeout_is_configurable_and_not_retried_by_default(run) -> None:
    run.side_effect = subprocess.TimeoutExpired(["claude"], timeout=7)

    with pytest.raises(RetryExhaustedError):
        ClaudeCodeCaller(timeout_seconds=7).call("system", "user")

    assert run.call_count == 1
    assert run.call_args.kwargs["timeout"] == 7


def test_factory_applies_cli_execution_policy() -> None:
    caller = create_llm_caller(
        {
            "model": {
                "backend": "claude_code",
                "review_model": "sonnet",
                "timeout_seconds": 240,
                "max_attempts": 2,
            }
        }
    )

    assert isinstance(caller, ClaudeCodeCaller)
    assert caller.timeout_seconds == 240
    assert caller.max_attempts == 2


@patch("yt2notion.models.llm.subprocess.run")
def test_claude_cli_error_preserves_provider_detail(run) -> None:
    run.side_effect = subprocess.CalledProcessError(
        1,
        ["claude"],
        output='{"result":"API Error: Unable to connect to API (ConnectionRefused)"}',
        stderr="",
    )

    with pytest.raises(ClaudeCodeError, match="ConnectionRefused"):
        ClaudeCodeCaller().call("system", "user")

    assert run.call_count == 1
