"""Tests for the Codex CLI text-call adapter."""

from __future__ import annotations

import errno
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yt2notion.models.codex_cli import CodexCLICaller, CodexCLIError
from yt2notion.models.llm import create_llm_caller
from yt2notion.retry import RetryExhaustedError


def _write_output(cmd: list[str], value: str) -> None:
    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
    output_path.write_text(value, encoding="utf-8")


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_call_invokes_codex_exec_and_returns_text(run) -> None:
    def _side_effect(cmd, **kwargs):
        _write_output(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    run.side_effect = _side_effect

    result = CodexCLICaller(model="gpt-5.2").call("system", "user")

    assert result == "ok"
    cmd = run.call_args.args[0]
    assert cmd[:2] == ["codex", "exec"]
    assert "-m" in cmd and "gpt-5.2" in cmd
    assert "--sandbox" in cmd and "read-only" in cmd


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_call_forwards_profile_and_workdir(run) -> None:
    def _side_effect(cmd, **kwargs):
        _write_output(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.4", profile="goodhope", workdir="/tmp/runtime")

    caller.call("system", "user")

    cmd = run.call_args.args[0]
    assert cmd[cmd.index("-p") + 1] == "goodhope"
    assert "--skip-git-repo-check" in cmd
    assert run.call_args.kwargs["cwd"] == "/tmp/runtime"


@patch("yt2notion.models.codex_cli.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_call_retries_empty_output(_sleep, run) -> None:
    attempts = iter(["", "ok"])

    def _side_effect(cmd, **kwargs):
        _write_output(cmd, next(attempts))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    run.side_effect = _side_effect

    assert CodexCLICaller().call("system", "user") == "ok"
    assert run.call_count == 2


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_call_reports_missing_binary(run) -> None:
    run.side_effect = FileNotFoundError("codex not found")

    with pytest.raises(CodexCLIError, match="not found"):
        CodexCLICaller().call("system", "user")


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_call_reports_invalid_workdir(run) -> None:
    workdir = "/tmp/does-not-exist-codex-runtime"
    run.side_effect = FileNotFoundError(errno.ENOENT, "No such file or directory", workdir)

    with pytest.raises(CodexCLIError, match="working directory not found"):
        CodexCLICaller(workdir=workdir).call("system", "user")


@patch("yt2notion.models.codex_cli.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_call_raises_after_retry_exhaustion(_sleep, run) -> None:
    run.side_effect = subprocess.CalledProcessError(1, "codex")

    with pytest.raises(RetryExhaustedError):
        CodexCLICaller().call("system", "user")
    assert run.call_count == 3


def test_factory_configures_codex_reasoning_effort() -> None:
    caller = create_llm_caller(
        {
            "model": {
                "backend": "codex_cli",
                "review_model": "gpt-5.4",
                "reasoning_effort": "medium",
            }
        }
    )

    assert isinstance(caller, CodexCLICaller)
    assert caller.reasoning_effort == "medium"
