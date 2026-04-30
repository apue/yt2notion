"""Tests for Codex CLI backend and caller (all subprocess calls mocked)."""

from __future__ import annotations

import errno
import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yt2notion.models import create_summarizer
from yt2notion.models.base import NoteDocument, VideoMeta
from yt2notion.models.codex_cli import CodexCLICaller, CodexCLIError, CodexCLIModel
from yt2notion.models.llm import create_llm_caller
from yt2notion.retry import RetryExhaustedError


def _write_output_from_cmd(cmd: list[str], text: str) -> None:
    output_path = Path(cmd[cmd.index("--output-last-message") + 1])
    output_path.write_text(text, encoding="utf-8")


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
    )


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_invokes_exec_and_returns_text(mock_run):
    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.2")
    result = caller.call("system", "user", max_tokens=100)

    assert result == "ok"
    cmd = mock_run.call_args[0][0]
    assert cmd[0:2] == ["codex", "exec"]
    assert "-m" in cmd and "gpt-5.2" in cmd
    assert "-c" in cmd and 'model_reasoning_effort="low"' in cmd
    assert "--sandbox" in cmd and "read-only" in cmd
    assert cmd[-1] == "-"
    assert mock_run.call_args.kwargs.get("timeout") == 300


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_passes_workdir_to_subprocess_run(mock_run):
    workdir = "/tmp/yt2notion-codex-runtime"

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.2", workdir=workdir)
    result = caller.call("system", "user")

    assert result == "ok"
    assert mock_run.call_args.kwargs.get("cwd") == workdir


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_passes_profile_to_exec(mock_run):
    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.4", profile="goodhope")
    result = caller.call("system", "user")

    assert result == "ok"
    cmd = mock_run.call_args[0][0]
    assert "-p" in cmd
    assert cmd[cmd.index("-p") + 1] == "goodhope"


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_skips_git_repo_check_when_workdir_is_set(mock_run):
    workdir = "/tmp/yt2notion-codex-runtime"

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.2", workdir=workdir)
    result = caller.call("system", "user")

    assert result == "ok"
    cmd = mock_run.call_args[0][0]
    assert "--skip-git-repo-check" in cmd


@patch("yt2notion.models.codex_cli.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_codex_caller_retries_on_called_process_error(mock_sleep, mock_run):
    call_count = {"n": 0}

    def _side_effect(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            raise subprocess.CalledProcessError(1, "codex")
        _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.2")
    result = caller.call("system", "user")

    assert result == "ok"
    assert mock_run.call_count == 2
    mock_sleep.assert_called_once()


@patch("yt2notion.models.codex_cli.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_codex_caller_retries_on_empty_output(mock_sleep, mock_run):
    call_count = {"n": 0}

    def _side_effect(cmd, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            _write_output_from_cmd(cmd, "   ")
        else:
            _write_output_from_cmd(cmd, "ok")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    caller = CodexCLICaller(model="gpt-5.2")
    result = caller.call("system", "user")

    assert result == "ok"
    assert mock_run.call_count == 2
    mock_sleep.assert_called_once()


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_no_retry_on_missing_binary(mock_run):
    mock_run.side_effect = FileNotFoundError("codex not found")
    caller = CodexCLICaller(model="gpt-5.2")
    with pytest.raises(CodexCLIError, match="not found"):
        caller.call("system", "user")
    assert mock_run.call_count == 1


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_caller_reports_invalid_workdir(mock_run):
    bad_workdir = "/tmp/does-not-exist-codex-runtime"
    mock_run.side_effect = FileNotFoundError(
        errno.ENOENT, "No such file or directory", bad_workdir
    )
    caller = CodexCLICaller(model="gpt-5.2", workdir=bad_workdir)

    with pytest.raises(CodexCLIError, match="working directory not found"):
        caller.call("system", "user")
    assert mock_run.call_count == 1


@patch("yt2notion.models.codex_cli.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_codex_caller_exhausts_retries(mock_sleep, mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(1, "codex")
    caller = CodexCLICaller(model="gpt-5.2")
    with pytest.raises(RetryExhaustedError):
        caller.call("system", "user")
    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 2


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_compose_guide_note_parses_json(mock_run, meta):
    payload = {"title": "Guide", "markdown": "# Guide", "tags": ["guide"], "variant": "a_guide"}

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(payload))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    model = CodexCLIModel(summarize_model="gpt-5.2", translate_model="gpt-5.2")
    result = model.compose_guide_note("transcript text", meta, target_chars=2000)

    assert result.title == "Guide"
    assert result.variant == "a_guide"


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_compose_longform_note_parses_json(mock_run, meta):
    payload = {"title": "Long", "markdown": "# Long", "tags": ["long"], "variant": "b_longform"}

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(payload))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    guide = NoteDocument(title="Guide", markdown="# Guide", tags=[], variant="a_guide")
    result = CodexCLIModel().compose_longform_note("transcript", guide, meta, target_chars=7000)

    assert result.title == "Long"
    assert result.variant == "b_longform"


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_compose_note_metadata_parses_json(mock_run, meta):
    payload = {
        "source_title": "Source",
        "stable_tags": ["stable"],
        "guide_tags": ["guide"],
        "longform_tags": ["long"],
        "source_summary": "summary",
        "source_topics": ["topic"],
    }

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(payload))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    guide = NoteDocument(title="Guide", markdown="# Guide", tags=[], variant="a_guide")
    long = NoteDocument(title="Long", markdown="# Long", tags=[], variant="b_longform")
    result = CodexCLIModel().compose_note_metadata(guide, long, meta)

    assert result.source_title == "Source"
    assert result.source_topics == ["topic"]


def test_create_llm_caller_codex_backend():
    caller = create_llm_caller({"model": {"backend": "codex_cli", "review_model": "gpt-5.4"}})
    assert isinstance(caller, CodexCLICaller)
    assert caller.reasoning_effort == "low"


def test_create_llm_caller_codex_backend_honors_reasoning_effort():
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


def test_create_llm_caller_openai_alias_maps_legacy_model_name():
    caller = create_llm_caller({"model": {"backend": "openai_api", "review_model": "haiku"}})
    assert isinstance(caller, CodexCLICaller)
    assert caller.model == "gpt-5.4"


def test_create_llm_caller_codex_backend_forwards_runtime_workdir():
    caller = create_llm_caller(
        {
            "model": {
                "backend": "codex_cli",
                "review_model": "gpt-5.4",
                "_runtime": {
                    "codex_workdir": "/tmp/runtime-agent-home",
                    "codex_profile": "goodhope",
                },
            }
        }
    )
    assert isinstance(caller, CodexCLICaller)
    assert caller.workdir == "/tmp/runtime-agent-home"
    assert caller.profile == "goodhope"


def test_create_summarizer_codex_backend_forwards_runtime_workdir():
    summarizer = create_summarizer(
        {
            "model": {
                "backend": "codex_cli",
                "summarize_model": "gpt-5.4",
                "translate_model": "gpt-5.4",
                "_runtime": {
                    "codex_workdir": "/tmp/runtime-agent-home",
                    "codex_profile": "goodhope",
                },
            },
        }
    )
    assert isinstance(summarizer, CodexCLIModel)
    assert summarizer.workdir == "/tmp/runtime-agent-home"
    assert summarizer.profile == "goodhope"
    assert summarizer._summarize_caller.workdir == "/tmp/runtime-agent-home"
    assert summarizer._summarize_caller.profile == "goodhope"
    assert summarizer._translate_caller.workdir == "/tmp/runtime-agent-home"
    assert summarizer._translate_caller.profile == "goodhope"
