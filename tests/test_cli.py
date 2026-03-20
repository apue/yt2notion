"""Tests for CLI entry point."""

from __future__ import annotations

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
        app, ["https://www.youtube.com/watch?v=abc", "-c", "/nonexistent/config.yaml"]
    )
    assert result.exit_code == 1
    assert "Configuration error" in result.output or "not found" in result.output


@patch("yt2notion.cli.load_config")
@patch("yt2notion.pipeline.run_pipeline")
def test_cli_dry_run(mock_pipeline, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    mock_pipeline.return_value = "dry run output"

    result = runner.invoke(
        app,
        ["https://www.youtube.com/watch?v=abc123", "--dry-run"],
    )
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
        ["https://www.youtube.com/watch?v=abc123", "--no-confirm", "-v"],
    )
    assert result.exit_code == 0
    call_kwargs = mock_pipeline.call_args
    assert call_kwargs.kwargs.get("verbose") is True
    assert call_kwargs.kwargs.get("no_confirm") is True
