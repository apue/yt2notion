"""Tests for pipeline orchestrator."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from yt2notion.config import AppConfig
from yt2notion.extract import ExtractionError
from yt2notion.models.base import ChineseContent, Section, Summary, VideoMeta


@pytest.fixture
def mock_meta():
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
        upload_date="20260319",
        duration_seconds=600,
        subtitles_available=True,
    )


@pytest.fixture
def mock_summary():
    return Summary(
        sections=[
            Section(title="Intro", timestamp="0:00", timestamp_seconds=0, summary="Introduction"),
        ],
        overall_summary="Test summary",
        suggested_tags=["test"],
    )


@pytest.fixture
def mock_chinese():
    return ChineseContent(
        overview="测试概要",
        key_points=[{"timestamp": "0:00", "title": "介绍", "summary": "测试"}],
        tags=["测试"],
        raw_markdown=(
            "## 概要\n\n测试概要\n\n## 关键节点\n\n- [0:00] **介绍**：测试\n\n## 标签\n\n测试"
        ),
    )


@pytest.fixture
def config(tmp_path):
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path / "workspace")}
    return cfg


@patch("yt2notion.pipeline.create_llm_caller")
@patch("yt2notion.pipeline.create_storage")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_pipeline_full_mock(
    mock_extract_meta,
    mock_extract_subs,
    mock_create_summarizer,
    mock_create_storage,
    mock_create_llm_caller,
    mock_meta,
    mock_summary,
    mock_chinese,
    config,
    tmp_path,
):
    mock_extract_meta.return_value = mock_meta

    # Create a real subtitle file
    srt_file = tmp_path / "abc123.en.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:05,000\nHello world\n")
    mock_extract_subs.return_value = srt_file

    mock_summarizer = MagicMock()
    mock_summarizer.summarize.return_value = mock_summary
    mock_summarizer.to_chinese.return_value = mock_chinese
    mock_create_summarizer.return_value = mock_summarizer

    mock_storage = MagicMock()
    mock_storage.save.return_value = "https://notion.so/page123"
    mock_create_storage.return_value = mock_storage

    # Mock LLM caller for entity extraction
    mock_caller = MagicMock()
    # caller.call(system_prompt, user_prompt, max_tokens=4000) returns JSON string
    mock_caller.call.return_value = (
        '{"entities": [], "domain": "General", "is_entity_centric": false, '
        '"entity_types": [], "relations": []}'
    )
    mock_create_llm_caller.return_value = mock_caller

    from yt2notion.pipeline import run_pipeline

    failed_file = tmp_path / "workspace" / "abc123" / "failed.json"
    failed_file.parent.mkdir(parents=True, exist_ok=True)
    failed_file.write_text("{}", encoding="utf-8")

    with patch("yt2notion.pipeline.typer.confirm") as mock_confirm:
        result = run_pipeline(
            "https://www.youtube.com/watch?v=abc123",
            config,
            no_confirm=True,
        )

    assert result == "https://notion.so/page123"
    mock_confirm.assert_not_called()
    mock_extract_meta.assert_called_once()
    mock_summarizer.summarize.assert_called_once()
    mock_summarizer.to_chinese.assert_called_once()
    mock_storage.save.assert_called_once()
    assert not failed_file.exists()


@patch("yt2notion.pipeline.create_llm_caller")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_pipeline_dry_run(
    mock_extract_meta,
    mock_extract_subs,
    mock_create_summarizer,
    mock_create_llm_caller,
    mock_meta,
    mock_summary,
    mock_chinese,
    config,
    tmp_path,
):
    mock_extract_meta.return_value = mock_meta

    srt_file = tmp_path / "abc123.en.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:05,000\nHello world\n")
    mock_extract_subs.return_value = srt_file

    mock_summarizer = MagicMock()
    mock_summarizer.summarize.return_value = mock_summary
    mock_summarizer.to_chinese.return_value = mock_chinese
    mock_create_summarizer.return_value = mock_summarizer

    # Mock LLM caller for entity extraction
    mock_caller = MagicMock()
    # caller.call(system_prompt, user_prompt, max_tokens=4000) returns JSON string
    mock_caller.call.return_value = (
        '{"entities": [], "domain": "General", "is_entity_centric": false, '
        '"entity_types": [], "relations": []}'
    )
    mock_create_llm_caller.return_value = mock_caller

    from yt2notion.pipeline import run_pipeline

    result = run_pipeline(
        "https://www.youtube.com/watch?v=abc123",
        config,
        dry_run=True,
    )

    assert "TestChannel" in result
    assert "Test Video" in result
    assert "概要" in result


@patch("yt2notion.pipeline.extract_metadata")
def test_pipeline_extract_error(mock_extract_meta, config):
    mock_extract_meta.side_effect = ExtractionError("No subtitles found")

    from yt2notion.pipeline import run_pipeline

    with pytest.raises(ExtractionError, match="No subtitles"):
        run_pipeline("https://www.youtube.com/watch?v=abc123", config)


@patch("yt2notion.pipeline.create_llm_caller")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.extract_subtitles")
@patch("yt2notion.pipeline.extract_metadata")
def test_pipeline_records_failure(
    mock_extract_meta,
    mock_extract_subs,
    mock_create_summarizer,
    mock_create_llm_caller,
    mock_meta,
    mock_summary,
    mock_chinese,
    config,
    tmp_path,
):
    mock_extract_meta.return_value = mock_meta

    srt_file = tmp_path / "abc123.en.srt"
    srt_file.write_text("1\n00:00:01,000 --> 00:00:05,000\nHello world\n")
    mock_extract_subs.return_value = srt_file

    mock_caller = MagicMock()
    mock_caller.call.return_value = (
        '{"entities": [], "domain": "General", "is_entity_centric": false, '
        '"entity_types": [], "relations": []}'
    )
    mock_create_llm_caller.return_value = mock_caller
    mock_create_summarizer.side_effect = RuntimeError("summary crashed")

    from yt2notion.pipeline import run_pipeline

    with pytest.raises(RuntimeError, match="summary crashed"):
        run_pipeline("https://www.youtube.com/watch?v=abc123", config)

    failed_file = tmp_path / "workspace" / "abc123" / "failed.json"
    assert failed_file.exists()
    data = failed_file.read_text(encoding="utf-8")
    assert '"step": "summarize"' in data
    assert '"url": "https://www.youtube.com/watch?v=abc123"' in data
    assert '"retries_exhausted": false' in data.lower()
