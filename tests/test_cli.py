"""Tests for CLI entry point."""

from __future__ import annotations

import json
from unittest.mock import patch

from typer.testing import CliRunner

from yt2notion.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "YouTube" in result.output


def test_cli_missing_config():
    result = runner.invoke(
        app, ["process", "https://www.youtube.com/watch?v=abc", "-c", "/nonexistent/config.yaml"]
    )
    # Typer returns 2 for usage errors
    assert result.exit_code in (1, 2)
    assert "Configuration error" in result.output or "not found" in result.output


@patch("yt2notion.cli.load_config")
@patch("yt2notion.pipeline.run_pipeline")
def test_cli_dry_run(mock_pipeline, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    mock_pipeline.return_value = "dry run output"

    result = runner.invoke(
        app,
        ["process", "https://www.youtube.com/watch?v=abc123", "--dry-run"],
    )
    # Typer may return 0 or other code for successful dry run
    if result.exit_code != 0:
        # If there's an error, print it for debugging
        print(result.output)
    assert result.exit_code == 0
    mock_pipeline.assert_called_once()
    call_kwargs = mock_pipeline.call_args
    assert call_kwargs.kwargs.get("dry_run") is True


@patch("yt2notion.cli.load_config")
@patch("yt2notion.pipeline.run_pipeline")
def test_cli_process_invocation(mock_pipeline, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    mock_pipeline.return_value = "https://notion.so/page123"

    result = runner.invoke(
        app,
        [
            "process",
            "https://www.youtube.com/watch?v=abc123",
            "-v",
            "--mode",
            "full",
        ],
    )
    # Typer may return 0 or other code depending on pipeline output
    if result.exit_code != 0:
        # If there's an error, print it for debugging
        print(result.output)
    assert result.exit_code == 0
    call_kwargs = mock_pipeline.call_args
    assert call_kwargs.kwargs.get("verbose") is True
    assert call_kwargs.kwargs.get("mode") == "full"


@patch("yt2notion.cli.load_config")
@patch("yt2notion.pipeline.prepare_content")
def test_cli_prepare_outputs_json(mock_prepare_content, mock_load_config, tmp_path):
    from yt2notion.config import AppConfig
    from yt2notion.models.base import ChineseContent, VideoMeta
    from yt2notion.pipeline import PreparedContent
    from yt2notion.workspace import Workspace

    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=ChineseContent(
            overview="测试概要",
            key_points=[{"timestamp": "0:00", "title": "介绍", "summary": "测试"}],
            tags=["测试"],
            raw_markdown="## 概要\n\n测试概要",
        ),
        transcript_segments=None,
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="summary",
    )

    result = runner.invoke(
        app,
        ["prepare", "https://www.youtube.com/watch?v=abc123", "--mode", "summary"],
    )

    assert result.exit_code == 0
    assert '"mode": "summary"' in result.output
    assert '"workspace_dir"' in result.output


@patch("yt2notion.cli.load_config")
@patch("yt2notion.pipeline.prepare_content")
def test_cli_prepare_full_mode_includes_transcript_markdown(
    mock_prepare_content, mock_load_config, tmp_path
):
    from yt2notion.config import AppConfig
    from yt2notion.models.base import ChineseContent, VideoMeta
    from yt2notion.pipeline import PreparedContent
    from yt2notion.workspace import Workspace

    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=ChineseContent(
            overview="测试概要",
            key_points=[{"timestamp": "0:00", "title": "介绍", "summary": "测试"}],
            tags=["测试"],
            raw_markdown="## 概要\n\n测试概要",
        ),
        transcript_segments=[
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 12,
                "text": "cleaned transcript",
                "source": "asr",
            }
        ],
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="full",
    )

    result = runner.invoke(
        app,
        ["prepare", "https://www.youtube.com/watch?v=abc123", "--mode", "full"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "full"
    assert payload["transcript_markdown"] is not None
    assert "cleaned transcript" in payload["transcript_markdown"]
