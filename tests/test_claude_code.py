"""Tests for Claude Code backend (all mocked)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from yt2notion.models._parsers import parse_chinese_markdown, parse_summary_json
from yt2notion.models.base import VideoMeta
from yt2notion.models.claude_code import ClaudeCodeError, ClaudeCodeModel

SAMPLE_SUMMARY_JSON = {
    "sections": [
        {
            "title": "Hip Joint Overview",
            "timestamp": "0:00",
            "timestamp_seconds": 0,
            "summary": "Explains the basic structure of the hip joint.",
        },
        {
            "title": "Strengthening Exercises",
            "timestamp": "2:04",
            "timestamp_seconds": 124,
            "summary": "Five exercises targeting the iliopsoas muscle.",
        },
    ],
    "overall_summary": "A comprehensive guide to hip flexor exercises.",
    "suggested_tags": ["hip mobility", "strength training"],
}

SAMPLE_CHINESE_MD = """\
## 概要

这是一个关于髋关节训练的视频，介绍了五个髂腰肌强化动作。

## 关键节点

- [0:00] **髋关节结构**：讲解髋关节基本结构
- [2:04] **强化训练**：五个针对髂腰肌的训练动作

## 标签

髋关节灵活性, 力量训练
"""


@pytest.fixture
def meta():
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
    )


def test_parse_summary_json_raw():
    result = parse_summary_json(json.dumps(SAMPLE_SUMMARY_JSON))
    assert len(result.sections) == 2
    assert result.sections[0].title == "Hip Joint Overview"
    assert result.sections[1].timestamp_seconds == 124
    assert result.overall_summary == "A comprehensive guide to hip flexor exercises."
    assert "hip mobility" in result.suggested_tags


def test_parse_summary_json_with_fence():
    fenced = f"```json\n{json.dumps(SAMPLE_SUMMARY_JSON)}\n```"
    result = parse_summary_json(fenced)
    assert len(result.sections) == 2


def test_parse_summary_json_invalid():
    from yt2notion.models._parsers import ParseError

    with pytest.raises(ParseError, match="Failed to parse"):
        parse_summary_json("not json at all")


def test_parse_chinese_markdown():
    result = parse_chinese_markdown(SAMPLE_CHINESE_MD)
    assert "髋关节" in result.overview
    assert len(result.key_points) == 2
    assert result.key_points[0]["timestamp"] == "0:00"
    assert result.key_points[0]["title"] == "髋关节结构"
    assert len(result.tags) == 2
    assert "力量训练" in result.tags
    assert result.raw_markdown == SAMPLE_CHINESE_MD


@patch("yt2notion.models.claude_code.subprocess.run")
def test_call_claude_args(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"result": json.dumps(SAMPLE_SUMMARY_JSON)}),
        stderr="",
    )
    model = ClaudeCodeModel(summarize_model="sonnet", translate_model="opus")
    model.summarize("transcript text", meta)

    cmd = mock_run.call_args[0][0]
    assert "claude" in cmd
    assert "-p" in cmd
    assert "--model" in cmd
    assert "sonnet" in cmd
    assert "--max-turns" in cmd
    assert "1" in cmd
    assert "--output-format" in cmd
    assert "json" in cmd


@patch("yt2notion.models.claude_code.subprocess.run")
def test_summarize_integration(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"result": json.dumps(SAMPLE_SUMMARY_JSON)}),
        stderr="",
    )
    model = ClaudeCodeModel()
    result = model.summarize("transcript text", meta)
    assert len(result.sections) == 2
    assert result.overall_summary


@patch("yt2notion.models.claude_code.subprocess.run")
def test_to_chinese_integration(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps({"result": SAMPLE_CHINESE_MD}),
        stderr="",
    )
    model = ClaudeCodeModel()
    summary = parse_summary_json(json.dumps(SAMPLE_SUMMARY_JSON))
    result = model.to_chinese(summary, meta)
    assert "髋关节" in result.overview
    assert len(result.key_points) == 2


@patch("yt2notion.models.claude_code.subprocess.run")
def test_claude_not_found(mock_run, meta):
    mock_run.side_effect = FileNotFoundError()
    model = ClaudeCodeModel()
    with pytest.raises(ClaudeCodeError, match="not found"):
        model.summarize("text", meta)


@patch("yt2notion.models.claude_code.subprocess.run")
def test_claude_cli_error(mock_run, meta):
    mock_run.side_effect = subprocess.CalledProcessError(1, "claude", stderr="error msg")
    model = ClaudeCodeModel()
    with pytest.raises(ClaudeCodeError, match="failed"):
        model.summarize("text", meta)
