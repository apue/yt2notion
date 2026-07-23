"""Tests for CLI entry point."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from yt2notion.cli import app

runner = CliRunner()


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "YouTube" in result.output
    assert "agent" not in result.output


def test_cli_missing_config():
    result = runner.invoke(
        app, ["process", "https://www.youtube.com/watch?v=abc", "-c", "/nonexistent/config.yaml"]
    )
    # Typer returns 2 for usage errors
    assert result.exit_code in (1, 2)
    assert "Configuration error" in result.output or "not found" in result.output


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_dry_run(mock_create_app, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    app_instance = MagicMock()
    app_instance.process.return_value = "dry run output"
    mock_create_app.return_value = app_instance

    result = runner.invoke(
        app,
        ["process", "https://www.youtube.com/watch?v=abc123", "--dry-run"],
    )
    # Typer may return 0 or other code for successful dry run
    if result.exit_code != 0:
        # If there's an error, print it for debugging
        print(result.output)
    assert result.exit_code == 0
    app_instance.process.assert_called_once()
    call_kwargs = app_instance.process.call_args
    assert call_kwargs.kwargs.get("dry_run") is True


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_process_invocation(mock_create_app, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    app_instance = MagicMock()
    app_instance.process.return_value = "https://notion.so/page123"
    mock_create_app.return_value = app_instance

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
    call_kwargs = app_instance.process.call_args
    assert call_kwargs.kwargs.get("verbose") is True
    assert call_kwargs.kwargs.get("mode") == "full"


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_prepare_outputs_bundle_json(mock_create_app, mock_load_config, tmp_path):
    from yt2notion.application import PreparedContent
    from yt2notion.config import AppConfig
    from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta
    from yt2notion.workspace import Workspace

    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    bundle = NoteBundle(
        source=NoteDocument(title="Source", markdown="# Source", tags=["stable"], variant="source"),
        guide=NoteDocument(title="Guide", markdown="# Guide", tags=["guide"], variant="a_guide"),
        longform=NoteDocument(title="Long", markdown="# Long", tags=["long"], variant="b_longform"),
        stable_tags=["stable"],
        source_topics=["topic"],
    )
    app_instance = MagicMock()
    app_instance.prepare.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        note_bundle=bundle,
        workspace=workspace,
        is_long=False,
    )
    mock_create_app.return_value = app_instance

    result = runner.invoke(
        app,
        ["prepare", "https://www.youtube.com/watch?v=abc123", "--mode", "summary"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "bundle"
    assert payload["workspace_dir"] == str(workspace.dir)
    assert payload["note_bundle"]["source"]["variant"] == "source"
    assert payload["note_bundle"]["guide"]["variant"] == "a_guide"
    assert payload["note_bundle"]["longform"]["variant"] == "b_longform"


@patch("yt2notion.media_transcribe.transcribe_media")
@patch("yt2notion.media_transcribe.resolve_media_transcribe_config_path")
@patch("yt2notion.cli.load_config")
def test_cli_transcribe_outputs_json(
    mock_load_config,
    mock_resolve_config,
    mock_transcribe_media,
    tmp_path,
):
    from yt2notion.config import AppConfig
    from yt2notion.media_transcribe import MediaTranscribeResult
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    config_path = tmp_path / "config.yaml"
    mock_resolve_config.return_value = config_path
    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    result_payload = MediaTranscribeResult(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://example.com/video",
        ),
        workspace=workspace,
        video_path=workspace.dir / "video.mp4",
        audio_path=workspace.dir / "audio.mp3",
        transcripts_path=workspace.dir / "transcripts.json",
        transcript_markdown_path=workspace.dir / "transcript.md",
    )
    mock_transcribe_media.return_value = result_payload

    result = runner.invoke(
        app,
        [
            "transcribe",
            "https://example.com/video",
            "--config",
            str(config_path),
            "--workspace-dir",
            str(tmp_path / "workspace"),
            "--no-video",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workspace_dir"] == str(workspace.dir)
    assert payload["transcript_markdown_path"] == str(workspace.dir / "transcript.md")
    mock_resolve_config.assert_called_once_with(str(config_path))
    mock_transcribe_media.assert_called_once()
    call_kwargs = mock_transcribe_media.call_args.kwargs
    assert call_kwargs["workspace_dir"] == str(tmp_path / "workspace")
    assert call_kwargs["keep_video"] is False
