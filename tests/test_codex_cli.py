"""Tests for Codex CLI backend and caller (all subprocess calls mocked)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from yt2notion.models.base import Summary, VideoMeta
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
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_codex_caller_exhausts_retries(mock_sleep, mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(1, "codex")
    caller = CodexCLICaller(model="gpt-5.2")
    with pytest.raises(RetryExhaustedError):
        caller.call("system", "user")
    assert mock_run.call_count == 3
    assert mock_sleep.call_count == 2


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_summarize_parses_json(mock_run, meta):
    sample_summary = {
        "sections": [
            {
                "title": "Intro",
                "timestamp": "0:00",
                "timestamp_seconds": 0,
                "summary": "Test summary",
            }
        ],
        "overall_summary": "Overall",
        "suggested_tags": ["tag"],
    }

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(sample_summary))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    model = CodexCLIModel(summarize_model="gpt-5.2", translate_model="gpt-5.2")
    result = model.summarize("transcript text", meta)

    assert len(result.sections) == 1
    assert result.sections[0].title == "Intro"
    assert result.overall_summary == "Overall"


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_to_chinese_parses_markdown(mock_run):
    sample_md = "## 概要\n\n测试概要\n\n## 关键节点\n\n- [0:00] **介绍**：测试\n\n## 标签\n\n测试"

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, sample_md)
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    model = CodexCLIModel(summarize_model="gpt-5.2", translate_model="gpt-5.2")
    summary = Summary(sections=[], overall_summary="overall", suggested_tags=[])
    content = model.to_chinese(summary, VideoMeta(video_id="x", title="t", channel="c", url="u"))

    assert "测试概要" in content.overview
    assert content.tags == ["测试"]


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_review_and_summarize_parses_combined_json(mock_run, meta):
    sample_summary = {
        "reviewed_transcript": "[0:00] cleaned transcript",
        "sections": [
            {
                "title": "Intro",
                "timestamp": "0:00",
                "timestamp_seconds": 0,
                "summary": "Test summary",
            }
        ],
        "overall_summary": "Overall",
        "suggested_tags": ["tag"],
    }

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(sample_summary))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    model = CodexCLIModel(summarize_model="gpt-5.2", translate_model="gpt-5.2")
    result = model.review_and_summarize("transcript text", meta)

    assert result.reviewed_transcript == "[0:00] cleaned transcript"
    assert result.summary.overall_summary == "Overall"


@patch("yt2notion.models.codex_cli.subprocess.run")
def test_codex_model_review_and_summarize_parses_json(mock_run, meta):
    payload = {
        "reviewed_transcript": "[0:00] cleaned transcript",
        "sections": [
            {
                "title": "Intro",
                "timestamp": "0:00",
                "timestamp_seconds": 0,
                "summary": "Test summary",
            }
        ],
        "overall_summary": "Overall",
        "suggested_tags": ["tag"],
    }

    def _side_effect(cmd, **kwargs):
        _write_output_from_cmd(cmd, json.dumps(payload))
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = _side_effect
    model = CodexCLIModel(summarize_model="gpt-5.2", translate_model="gpt-5.2")
    result = model.review_and_summarize("raw transcript", meta)

    assert result.reviewed_transcript == "[0:00] cleaned transcript"
    assert result.summary.overall_summary == "Overall"


def test_create_llm_caller_codex_backend():
    caller = create_llm_caller({"model": {"backend": "codex_cli", "review_model": "gpt-5.2"}})
    assert isinstance(caller, CodexCLICaller)
    assert caller.reasoning_effort == "low"


def test_create_llm_caller_codex_backend_honors_reasoning_effort():
    caller = create_llm_caller(
        {
            "model": {
                "backend": "codex_cli",
                "review_model": "gpt-5.2",
                "reasoning_effort": "medium",
            }
        }
    )
    assert isinstance(caller, CodexCLICaller)
    assert caller.reasoning_effort == "medium"


def test_create_llm_caller_openai_alias_maps_legacy_model_name():
    caller = create_llm_caller({"model": {"backend": "openai_api", "review_model": "haiku"}})
    assert isinstance(caller, CodexCLICaller)
    assert caller.model == "gpt-5.2"
