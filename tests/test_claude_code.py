"""Tests for Claude Code backend."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import patch

import pytest

from yt2notion.models.base import NoteDocument, VideoMeta
from yt2notion.models.claude_code import ClaudeCodeError, ClaudeCodeModel
from yt2notion.retry import RetryExhaustedError

GUIDE_JSON = {"title": "Guide", "markdown": "# Guide", "tags": ["guide"], "variant": "a_guide"}
LONG_JSON = {"title": "Long", "markdown": "# Long", "tags": ["long"], "variant": "b_longform"}
META_JSON = {
    "source_title": "Source",
    "stable_tags": ["stable"],
    "guide_tags": ["guide"],
    "longform_tags": ["long"],
    "source_summary": "summary",
    "source_topics": ["topic"],
}


@pytest.fixture
def meta() -> VideoMeta:
    return VideoMeta(video_id="abc123", title="Test Video", channel="TestChannel", url="u")


@patch("yt2notion.models.claude_code.subprocess.run")
def test_compose_guide_note_invokes_claude_and_parses_json(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"result": json.dumps(GUIDE_JSON)}), stderr=""
    )
    result = ClaudeCodeModel(translate_model="opus").compose_guide_note(
        "transcript text", meta, target_chars=2000
    )

    assert result.variant == "a_guide"
    cmd = mock_run.call_args.args[0]
    assert cmd[:2] == ["claude", "-p"]
    assert "opus" in cmd
    assert mock_run.call_args.kwargs["timeout"] == 120


@patch("yt2notion.models.claude_code.subprocess.run")
def test_compose_longform_note_parses_json(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"result": json.dumps(LONG_JSON)}), stderr=""
    )
    guide = NoteDocument(title="Guide", markdown="# Guide", tags=[], variant="a_guide")
    result = ClaudeCodeModel().compose_longform_note("transcript", guide, meta, target_chars=7000)

    assert result.variant == "b_longform"


@patch("yt2notion.models.claude_code.subprocess.run")
def test_compose_note_metadata_parses_json(mock_run, meta):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps({"result": json.dumps(META_JSON)}), stderr=""
    )
    guide = NoteDocument(title="Guide", markdown="# Guide", tags=[], variant="a_guide")
    long = NoteDocument(title="Long", markdown="# Long", tags=[], variant="b_longform")
    result = ClaudeCodeModel().compose_note_metadata(guide, long, meta)

    assert result.source_title == "Source"


@patch("yt2notion.models.claude_code.subprocess.run")
def test_claude_not_found(mock_run, meta):
    mock_run.side_effect = FileNotFoundError()
    with pytest.raises(ClaudeCodeError, match="not found"):
        ClaudeCodeModel().compose_guide_note("text", meta, target_chars=2000)


@patch("yt2notion.models.claude_code.subprocess.run")
@patch("yt2notion.retry.time.sleep", return_value=None)
def test_claude_cli_error_exhausts_retries(mock_sleep, mock_run, meta):
    mock_run.side_effect = subprocess.CalledProcessError(1, "claude", stderr="error msg")
    with pytest.raises(RetryExhaustedError):
        ClaudeCodeModel().compose_guide_note("text", meta, target_chars=2000)
