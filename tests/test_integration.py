"""Integration test: full pipeline with fixture files, all external calls mocked."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

from yt2notion.config import AppConfig
from yt2notion.pipeline import run_pipeline

FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _load_fixture(name: str) -> str:
    return (FIXTURES_DIR / name).read_text(encoding="utf-8")


def _make_config(tmp_path: Path) -> AppConfig:
    config = AppConfig()
    config.workspace = {"base_dir": str(tmp_path / "workspace")}
    return config


@patch("yt2notion.pipeline.create_storage")
@patch("yt2notion.models.claude_code.subprocess.run")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_full_pipeline_with_fixtures(
    mock_extract_meta,
    mock_extract_subs,
    mock_claude_run,
    mock_create_storage,
    tmp_path,
    sample_srt,
    sample_meta,
):
    # 1. Setup extraction mocks
    mock_extract_meta.return_value = sample_meta
    mock_extract_subs.return_value = sample_srt

    # 2. Setup claude -p mock (two calls: summarize + to_chinese)
    summary_json = _load_fixture("sample_summary_response.json")
    chinese_md = _load_fixture("sample_chinese_response.md")

    call_count = 0

    def claude_side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # summarize call
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps({"result": summary_json}),
                stderr="",
            )
        else:
            # to_chinese call
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps({"result": chinese_md}),
                stderr="",
            )

    mock_claude_run.side_effect = claude_side_effect

    # 3. Setup storage mock
    mock_storage = MagicMock()
    mock_storage.save.return_value = "https://notion.so/test-page"
    mock_create_storage.return_value = mock_storage

    # 4. Run pipeline
    config = _make_config(tmp_path)
    result = run_pipeline(
        "https://www.youtube.com/watch?v=abc123",
        config,
        no_confirm=True,
    )

    # 5. Verify
    assert result == "https://notion.so/test-page"

    # Storage was called with ChineseContent containing source info
    save_call = mock_storage.save.call_args
    content = save_call[0][0]
    metadata = save_call[0][1]

    # Verify content has key points with correct timestamps
    assert len(content.key_points) == 3
    assert content.key_points[0]["timestamp"] == "0:00"
    assert content.key_points[1]["timestamp"] == "2:04"

    # Verify tags are in Chinese
    assert "髋关节灵活性" in content.tags

    # Verify metadata passed through
    assert metadata.channel == "FitnessPro"
    assert metadata.video_id == "abc123"


@patch("yt2notion.models.claude_code.subprocess.run")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_dry_run_includes_credit(
    mock_extract_meta,
    mock_extract_subs,
    mock_claude_run,
    tmp_path,
    sample_srt,
    sample_meta,
):
    mock_extract_meta.return_value = sample_meta
    mock_extract_subs.return_value = sample_srt

    summary_json = _load_fixture("sample_summary_response.json")
    chinese_md = _load_fixture("sample_chinese_response.md")

    call_count = 0

    def claude_side_effect(cmd, **kwargs):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps({"result": summary_json}),
                stderr="",
            )
        else:
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=0,
                stdout=json.dumps({"result": chinese_md}),
                stderr="",
            )

    mock_claude_run.side_effect = claude_side_effect

    config = _make_config(tmp_path)
    result = run_pipeline(
        "https://www.youtube.com/watch?v=abc123",
        config,
        dry_run=True,
    )

    # Dry run should include credit info
    assert "FitnessPro" in result
    assert "5 Hip Flexor Exercises You Need" in result
    assert "youtube.com" in result
    # Should include Chinese content
    assert "概要" in result
    assert "髋关节" in result
