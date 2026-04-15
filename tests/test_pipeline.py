"""Tests for pipeline orchestrator."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from yt2notion.cli import app
from yt2notion.config import AppConfig
from yt2notion.extract import ExtractionError
from yt2notion.models.base import (
    ChineseContent,
    EntityResult,
    NoteBundle,
    NoteDocument,
    Section,
    Summary,
    VideoMeta,
)
from yt2notion.process import SubtitleEntry
from yt2notion.segment import Segment
from yt2notion.transcribe.errors import (
    TranscriptionError,
    TranscriptionQuotaError,
    TranscriptionServerError,
)

runner = CliRunner()


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


@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline._summarize_short_asr_single_pass")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_summary_mode_uses_single_pass_asr_summary(
    mock_step_download,
    mock_download_audio,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_review,
    mock_download_webpage_transcript,
    mock_create_summarizer,
    mock_single_pass_summary,
    mock_step_extract,
    mock_meta,
    mock_summary,
    mock_chinese,
    config,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_download_audio.return_value = None
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "raw asr text",
            "source": "asr",
        }
    ]
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )

    mock_summarizer = MagicMock()
    mock_create_summarizer.return_value = mock_summarizer
    mock_single_pass_summary.return_value = mock_chinese

    from yt2notion.pipeline import prepare_content

    prepared = prepare_content("https://example.com/video", config, mode="summary")

    assert prepared.output_mode == "summary"
    assert prepared.transcript_segments is None
    mock_step_review.assert_not_called()
    mock_step_extract.assert_called_once()
    mock_single_pass_summary.assert_called_once()


@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline.segment_transcript")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_uses_webpage_transcript_before_audio(
    mock_step_download,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_segment_transcript,
    mock_step_extract,
    mock_meta,
    mock_chinese,
    config,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = True
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )

    subtitles_dir = Path(config.workspace["base_dir"]) / mock_meta.video_id
    subtitles_dir.mkdir(parents=True, exist_ok=True)
    (subtitles_dir / "subtitles.srt").write_text(
        "1\n00:00:00,000 --> 00:01:00,000\nHello\n",
        encoding="utf-8",
    )

    mock_summarizer = MagicMock()
    mock_summarizer.summarize.return_value = Summary(
        sections=[Section(title="Intro", timestamp="0:00", timestamp_seconds=0, summary="Hello")],
        overall_summary="Hello",
        suggested_tags=["test"],
    )
    mock_summarizer.to_chinese.return_value = mock_chinese

    with patch("yt2notion.pipeline.create_summarizer", return_value=mock_summarizer):
        from yt2notion.pipeline import prepare_content

        prepared = prepare_content("https://example.com/podcast", config, mode="summary")

    assert prepared.transcript_segments is None
    mock_download_webpage_transcript.assert_called_once()
    mock_download_audio.assert_not_called()
    mock_segment_transcript.assert_not_called()
    mock_step_extract.assert_not_called()


@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_full_mode_keeps_reviewed_transcript(
    mock_step_download,
    mock_download_audio,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_review,
    mock_step_extract,
    mock_meta,
    mock_chinese,
    config,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_audio.return_value = None
    mock_step_segment.return_value = []
    transcripts = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "raw asr text",
            "source": "asr",
        }
    ]
    reviewed = [{**transcripts[0], "text": "cleaned text"}]
    mock_step_transcribe.return_value = transcripts
    mock_step_review.return_value = reviewed
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )

    with patch("yt2notion.pipeline._step_summarize", return_value=mock_chinese) as mock_summarize:
        from yt2notion.pipeline import prepare_content

        prepared = prepare_content("https://example.com/video", config, mode="full")

    assert prepared.output_mode == "full"
    assert prepared.transcript_segments == reviewed
    mock_step_review.assert_called_once()
    mock_summarize.assert_called_once()


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

    result = run_pipeline(
        "https://www.youtube.com/watch?v=abc123",
        config,
    )

    assert result == "https://notion.so/page123"
    mock_extract_meta.assert_called_once()
    mock_summarizer.summarize.assert_called_once()
    mock_summarizer.to_chinese.assert_called_once()
    mock_storage.save.assert_called_once()
    assert not failed_file.exists()


@patch("yt2notion.pipeline.create_storage")
@patch("yt2notion.pipeline.prepare_content")
def test_run_pipeline_bundle_mode_publishes_to_obsidian(
    mock_prepare_content,
    mock_create_storage,
    config,
    tmp_path,
):
    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    config.storage = {
        "backend": "obsidian",
        "obsidian": {"vault_path": str(tmp_path / "vault")},
    }
    config.output["note_mode"] = "source_ab_bundle"

    workspace = Workspace(tmp_path / "workspace", "abc123")
    bundle = NoteBundle(
        source=NoteDocument(
            title="Test Video",
            markdown="# Source",
            tags=["AI"],
            variant="source",
        ),
        guide=NoteDocument(
            title="Test Video - 导读",
            markdown="# Guide",
            tags=["AI", "guide"],
            variant="a_guide",
        ),
        longform=NoteDocument(
            title="Test Video - 扩展",
            markdown="# Longform",
            tags=["AI", "longform"],
            variant="b_longform",
        ),
        stable_tags=["AI"],
        source_topics=["topic"],
    )
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=None,
        transcript_segments=None,
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="summary",
        note_bundle=bundle,
    )

    mock_storage = MagicMock()
    mock_storage.save_note_bundle.return_value = "/vault/yt2notion/summaries/Test Video.md"
    mock_create_storage.return_value = mock_storage

    result = run_pipeline("https://www.youtube.com/watch?v=abc123", config)

    assert result == "/vault/yt2notion/summaries/Test Video.md"
    mock_create_storage.assert_called_once()
    mock_storage.save_note_bundle.assert_called_once()
    mock_storage.save.assert_not_called()


@patch("yt2notion.pipeline.create_storage")
@patch("yt2notion.pipeline.prepare_content")
def test_run_pipeline_bundle_mode_rejects_non_obsidian_backend(
    mock_prepare_content,
    mock_create_storage,
    config,
    tmp_path,
):
    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    config.storage = {
        "backend": "notion",
        "notion": {"token": "x", "database_id": "y"},
    }
    config.output["note_mode"] = "source_ab_bundle"

    workspace = Workspace(tmp_path / "workspace", "abc123")
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=None,
        transcript_segments=None,
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="summary",
        note_bundle=NoteBundle(
            source=NoteDocument(
                title="Test Video",
                markdown="# Source",
                tags=["AI"],
                variant="source",
            ),
            guide=NoteDocument(
                title="Test Video - 导读",
                markdown="# Guide",
                tags=["AI", "guide"],
                variant="a_guide",
            ),
            longform=NoteDocument(
                title="Test Video - 扩展",
                markdown="# Longform",
                tags=["AI", "longform"],
                variant="b_longform",
            ),
            stable_tags=["AI"],
            source_topics=["topic"],
        ),
    )

    with pytest.raises(ValueError, match="obsidian"):
        run_pipeline("https://www.youtube.com/watch?v=abc123", config)

    mock_create_storage.assert_not_called()


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


@patch("yt2notion.pipeline._step_summarize")
@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_emits_progress_callbacks_for_key_steps_summary_mode(
    mock_step_download,
    mock_download_audio,
    mock_step_segment,
    mock_step_transcribe,
    mock_download_webpage_transcript,
    mock_step_review,
    mock_step_extract,
    mock_step_summarize,
    mock_meta,
    mock_chinese,
    config,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_download_audio.return_value = None
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "raw asr text",
            "source": "asr",
        }
    ]
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )
    mock_step_review.return_value = mock_step_transcribe.return_value
    mock_step_summarize.return_value = mock_chinese

    from yt2notion.pipeline import prepare_content

    events: list[tuple[str, str, str | None]] = []
    prepare_content(
        "https://example.com/video",
        config,
        mode="summary",
        progress_callback=lambda step, event, message=None: events.append((step, event, message)),
    )

    assert events == [
        ("download", "started", None),
        ("download", "completed", None),
        ("segment", "started", None),
        ("segment", "completed", None),
        ("transcribe", "started", None),
        ("transcribe", "completed", None),
        ("extract", "started", None),
        ("extract", "completed", None),
        ("summarize", "started", None),
        ("summarize", "completed", None),
    ]

    mock_step_review.assert_not_called()


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_bundle_mode_builds_note_bundle(
    mock_step_download,
    mock_download_audio,
    mock_step_segment,
    mock_step_transcribe,
    mock_download_webpage_transcript,
    mock_step_review,
    mock_step_extract,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    tmp_path,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_download_audio.return_value = None
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "raw asr text",
            "source": "asr",
        }
    ]
    reviewed_segments = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "cleaned asr text",
            "source": "asr",
        }
    ]
    mock_step_review.return_value = reviewed_segments
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = NoteBundle(
        source=NoteDocument(
            title="Ferrari",
            markdown="# Ferrari",
            tags=["法拉利"],
            variant="source",
        ),
        guide=NoteDocument(
            title="Ferrari 导读",
            markdown="# Ferrari 导读",
            tags=["法拉利", "导读版"],
            variant="a_guide",
        ),
        longform=NoteDocument(
            title="Ferrari 扩展",
            markdown="# Ferrari 扩展",
            tags=["法拉利", "扩展版"],
            variant="b_longform",
        ),
        stable_tags=["法拉利", "赛车"],
        source_topics=["赛车文化", "品牌叙事"],
    )

    from yt2notion.pipeline import prepare_content

    config.output["note_mode"] = "source_ab_bundle"
    prepared = prepare_content(
        "https://example.com/video",
        config,
        mode="summary",
        workspace_dir=str(tmp_path / "workspace"),
    )

    assert prepared.note_bundle is not None
    assert prepared.chinese_content is None
    assert (prepared.workspace.dir / "note_bundle.json").exists()
    mock_create_summarizer.assert_called_once()
    mock_build_note_bundle.assert_called_once()
    mock_step_review.assert_called_once()
    assert mock_build_note_bundle.call_args.args[0] == reviewed_segments


@patch("yt2notion.pipeline._step_download")
def test_prepare_content_bundle_mode_rejects_full_mode_early(
    mock_step_download,
    mock_meta,
    config,
):
    from yt2notion.pipeline import prepare_content

    config.output["note_mode"] = "source_ab_bundle"

    with pytest.raises(ValueError, match="source_ab_bundle"):
        prepare_content("https://example.com/video", config, mode="full")

    mock_step_download.assert_not_called()


@patch("yt2notion.pipeline.prepare_content")
def test_cli_prepare_bundle_mode_outputs_note_bundle(mock_prepare_content, tmp_path):
    from yt2notion.config import AppConfig
    from yt2notion.pipeline import PreparedContent
    from yt2notion.workspace import Workspace

    workspace = Workspace(tmp_path, "abc123")
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=None,
        transcript_segments=None,
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="summary",
        note_bundle=NoteBundle(
            source=NoteDocument(
                title="Ferrari",
                markdown="# Ferrari",
                tags=["法拉利"],
                variant="source",
            ),
            guide=NoteDocument(
                title="Ferrari 导读",
                markdown="# Ferrari 导读",
                tags=["法拉利", "导读版"],
                variant="a_guide",
            ),
            longform=NoteDocument(
                title="Ferrari 扩展",
                markdown="# Ferrari 扩展",
                tags=["法拉利", "扩展版"],
                variant="b_longform",
            ),
            stable_tags=["法拉利", "赛车"],
            source_topics=["赛车文化", "品牌叙事"],
        ),
    )

    with patch("yt2notion.cli.load_config", return_value=AppConfig()):
        result = runner.invoke(
            app,
            ["prepare", "https://www.youtube.com/watch?v=abc123", "--mode", "summary"],
        )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["note_bundle"] is not None
    assert payload["summary"] is None


@patch("yt2notion.pipeline._step_summarize")
@patch("yt2notion.pipeline._step_extract")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._review_transcript_with_summary_context")
@patch("yt2notion.pipeline._is_long_content")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_emits_review_progress_callbacks_in_full_long_deferred_mode(
    mock_step_download,
    mock_download_audio,
    mock_step_segment,
    mock_step_transcribe,
    mock_download_webpage_transcript,
    mock_is_long_content,
    mock_deferred_review,
    mock_step_review,
    mock_step_extract,
    mock_step_summarize,
    mock_meta,
    mock_chinese,
    config,
):
    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_download_audio.return_value = None
    mock_step_segment.return_value = []
    transcripts = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 300,
            "text": "raw asr text",
            "source": "asr",
        }
    ]
    reviewed = [{**transcripts[0], "text": "cleaned text"}]
    mock_step_transcribe.return_value = transcripts
    mock_step_review.return_value = reviewed
    mock_is_long_content.return_value = True
    mock_deferred_review.return_value = reviewed
    mock_step_extract.return_value = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )
    mock_step_summarize.return_value = mock_chinese

    from yt2notion.pipeline import prepare_content

    events: list[tuple[str, str, str | None]] = []
    prepare_content(
        "https://example.com/video",
        config,
        mode="full",
        progress_callback=lambda step, event, message=None: events.append((step, event, message)),
    )

    assert events == [
        ("download", "started", None),
        ("download", "completed", None),
        ("segment", "started", None),
        ("segment", "completed", None),
        ("transcribe", "started", None),
        ("transcribe", "completed", None),
        ("extract", "started", None),
        ("extract", "completed", None),
        ("summarize", "started", None),
        ("summarize", "completed", None),
        ("review", "started", None),
        ("review", "completed", None),
    ]

    mock_step_review.assert_not_called()
    mock_deferred_review.assert_called_once()


@patch("yt2notion.pipeline.prepare_content")
def test_run_pipeline_dry_run_full_includes_transcript(mock_prepare_content, config):
    from pathlib import Path

    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    workspace = Workspace(Path(config.workspace["base_dir"]), "abc123")
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
                "end_seconds": 10,
                "text": "cleaned text",
                "source": "asr",
            }
        ],
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="full",
    )

    result = run_pipeline("https://example.com/video", config, dry_run=True, mode="full")

    assert "## 概要" in result
    assert "## 逐字稿" in result
    assert "cleaned text" in result


@patch("yt2notion.pipeline.prepare_content")
@patch("yt2notion.pipeline.create_storage")
def test_run_pipeline_emits_publish_progress_callbacks(
    mock_create_storage,
    mock_prepare_content,
    config,
):
    from pathlib import Path

    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    workspace = Workspace(Path(config.workspace["base_dir"]), "abc123")
    mock_prepare_content.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        chinese_content=ChineseContent(
            overview="测试概要",
            key_points=[],
            tags=[],
            raw_markdown="## 概要\n\n测试概要",
        ),
        transcript_segments=None,
        entities=None,
        workspace=workspace,
        is_long=False,
        output_mode="summary",
    )

    mock_storage = MagicMock()
    mock_storage.save.return_value = "https://notion.so/page123"
    mock_create_storage.return_value = mock_storage

    events: list[tuple[str, str, str | None]] = []
    result = run_pipeline(
        "https://example.com/video",
        config,
        progress_callback=lambda step, event, message=None: events.append((step, event, message)),
    )

    assert result == "https://notion.so/page123"
    assert events == [
        ("publish", "started", None),
        ("publish", "completed", None),
    ]
    assert mock_prepare_content.call_args.kwargs["progress_callback"] is not None


def test_rebase_chunk_entries_drops_overlap_duplicates():
    from yt2notion.pipeline import _rebase_chunk_entries

    entries = [
        SubtitleEntry(start_seconds=0.0, end_seconds=0.6, text="drop-left-overlap"),
        SubtitleEntry(start_seconds=1.0, end_seconds=3.0, text="keep-middle"),
        SubtitleEntry(start_seconds=300.0, end_seconds=301.0, text="drop-right-overlap"),
    ]

    rebased = _rebase_chunk_entries(
        entries,
        {
            "start_seconds": 300,
            "end_seconds": 600,
        },
    )

    assert [entry.text for entry in rebased] == ["keep-middle"]
    assert rebased[0].start_seconds == pytest.approx(300.5)
    assert rebased[0].end_seconds == pytest.approx(302.5)


def test_redistribute_reviewed_text_respects_actual_group_boundaries():
    from yt2notion.pipeline import _merge_segments_into_groups, _redistribute_reviewed_text

    segments = [
        {
            "title": f"S{i + 1}",
            "start_seconds": i * 10,
            "end_seconds": (i + 1) * 10,
            "text": "segment",
            "source": "asr",
        }
        for i in range(7)
    ]
    groups = _merge_segments_into_groups(segments)
    assert [group["segment_count"] for group in groups] == [6, 1]

    reviewed = _redistribute_reviewed_text(
        segments,
        groups,
        ["FIRST-GROUP-REVIEWED", "SECOND-GROUP-REVIEWED"],
    )

    assert reviewed[-1]["text"] == "SECOND-GROUP-REVIEWED"
    for seg in reviewed[:-1]:
        assert "SECOND-GROUP-REVIEWED" not in seg["text"]


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_transcriber")
@patch("yt2notion.segment._split_by_duration")
def test_transcribe_from_audio_chunks_long_full_audio(
    mock_split_by_duration,
    mock_create_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake audio")

    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 650

    chunk_paths = [tmp_path / "chunk1.mp3", tmp_path / "chunk2.mp3", tmp_path / "chunk3.mp3"]
    mock_split_audio.return_value = chunk_paths

    transcriber = MagicMock()
    transcriber.transcribe.side_effect = [
        [SubtitleEntry(start_seconds=299.2, end_seconds=300.0, text="chunk-1-edge")],
        [
            SubtitleEntry(start_seconds=0.0, end_seconds=0.6, text="drop-overlap"),
            SubtitleEntry(start_seconds=1.0, end_seconds=3.0, text="chunk-2-main"),
        ],
        [SubtitleEntry(start_seconds=1.0, end_seconds=5.0, text="chunk-3-main")],
    ]
    mock_create_transcriber.return_value = transcriber
    mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
        Segment(
            title="Part 1",
            start_seconds=int(entries[0].start_seconds),
            end_seconds=int(entries[-1].end_seconds),
            text=" | ".join(entry.text for entry in entries),
        )
    ]

    from yt2notion.pipeline import _transcribe_from_audio
    from yt2notion.workspace import Workspace

    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)

    result = _transcribe_from_audio(
        audio_path,
        [],
        mock_meta,
        {
            "extract": {"asr": {"backend": "remote"}},
            "output": {"max_segment_seconds": 300},
        },
        workspace,
        verbose=False,
    )

    assert mock_split_audio.called
    assert transcriber.transcribe.call_count == 3
    assert result == [
        {
            "title": "Part 1",
            "start_seconds": 299,
            "end_seconds": 604,
            "text": "chunk-1-edge | chunk-2-main | chunk-3-main",
            "source": "asr",
        }
    ]


@pytest.mark.parametrize("error_cls", [TranscriptionQuotaError, TranscriptionServerError])
@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_fallback_transcriber")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_falls_back_on_retryable_groq_errors(
    mock_create_transcriber,
    mock_create_fallback_transcriber,
    mock_split_audio,
    error_cls,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)
    stale_chunk_dir = ws.dir / "full_audio_chunks"
    stale_chunk_dir.mkdir(parents=True, exist_ok=True)
    (stale_chunk_dir / "chunk_001.mp3").write_bytes(b"stale")

    segment_file = ws.dir / "segments" / "segment_001.mp3"
    segment_file.parent.mkdir(parents=True, exist_ok=True)
    segment_file.write_bytes(b"segment")
    mock_split_audio.side_effect = [[segment_file], [segment_file]]

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.side_effect = error_cls("retryable")
    fallback = MagicMock()
    fallback.max_upload_bytes = None
    fallback.transcribe.return_value = [
        SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="fallback text"),
    ]
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.return_value = fallback

    result = _step_transcribe(
        ws,
        mock_meta,
        [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
        {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
        verbose=False,
    )

    assert result[0]["text"] == "fallback text"
    assert ws.asr_fallback_used() is True
    assert mock_split_audio.call_count == 2
    assert primary.transcribe.call_count == 1
    assert fallback.transcribe.call_count == 1
    assert not stale_chunk_dir.exists()


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_fallback_transcriber")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_does_not_fallback_for_non_retryable_transcription_error(
    mock_create_transcriber,
    mock_create_fallback_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)

    segment_file = ws.dir / "segments" / "segment_001.mp3"
    segment_file.parent.mkdir(parents=True, exist_ok=True)
    segment_file.write_bytes(b"segment")
    mock_split_audio.return_value = [segment_file]

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.side_effect = TranscriptionError("bad request")
    fallback = MagicMock()
    fallback.max_upload_bytes = None
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.return_value = fallback

    with pytest.raises(TranscriptionError, match="bad request"):
        _step_transcribe(
            ws,
            mock_meta,
            [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
            {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
            verbose=False,
        )

    assert fallback.transcribe.call_count == 0
    assert ws.asr_fallback_used() is False


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_fallback_transcriber")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_does_not_evaluate_fallback_config_when_primary_succeeds(
    mock_create_transcriber,
    mock_create_fallback_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)

    segment_file = ws.dir / "segments" / "segment_001.mp3"
    segment_file.parent.mkdir(parents=True, exist_ok=True)
    segment_file.write_bytes(b"segment")
    mock_split_audio.return_value = [segment_file]

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.return_value = [
        SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="primary ok"),
    ]
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.side_effect = ValueError("bad fallback config")

    result = _step_transcribe(
        ws,
        mock_meta,
        [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
        {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
        verbose=False,
    )

    assert result[0]["text"] == "primary ok"
    mock_create_fallback_transcriber.assert_not_called()


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_fallback_transcriber")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_propagates_retryable_error_when_no_fallback_configured(
    mock_create_transcriber,
    mock_create_fallback_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)

    segment_file = ws.dir / "segments" / "segment_001.mp3"
    segment_file.parent.mkdir(parents=True, exist_ok=True)
    segment_file.write_bytes(b"segment")
    mock_split_audio.return_value = [segment_file]

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.side_effect = TranscriptionQuotaError("quota")
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.return_value = None

    with pytest.raises(TranscriptionQuotaError, match="quota"):
        _step_transcribe(
            ws,
            mock_meta,
            [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
            {"extract": {"asr": {"backend": "groq"}}},
            verbose=False,
        )

    assert ws.asr_fallback_used() is False


@patch("yt2notion.audio.split_audio")
def test_transcribe_full_audio_fast_path_when_file_fits_upload_budget(
    mock_split_audio,
    mock_meta,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_full_audio_entries

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"x" * 1024)
    mock_meta.duration_seconds = 3600

    transcriber = MagicMock()
    transcriber.max_upload_bytes = 2048
    transcriber.transcribe.return_value = [
        SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="single request"),
    ]

    entries = _transcribe_full_audio_entries(
        audio_path,
        mock_meta,
        {
            "extract": {"asr": {"backend": "groq", "chunk_seconds": 300}},
            "output": {"max_segment_seconds": 300},
        },
        transcriber,
        language=None,
        verbose=False,
    )

    assert [entry.text for entry in entries] == ["single request"]
    transcriber.transcribe.assert_called_once_with(audio_path, language=None)
    mock_split_audio.assert_not_called()


@patch("yt2notion.audio.split_audio")
def test_transcribe_full_audio_oversize_short_clip_does_not_direct_upload(
    mock_split_audio,
    mock_meta,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_full_audio_entries

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"x" * 200)
    mock_meta.duration_seconds = 20

    transcriber = MagicMock()
    transcriber.max_upload_bytes = 100
    transcriber.transcribe.side_effect = AssertionError(
        "must not direct-upload oversize full audio"
    )

    with pytest.raises(TranscriptionError, match="minimum chunk size"):
        _transcribe_full_audio_entries(
            audio_path,
            mock_meta,
            {
                "extract": {"asr": {"backend": "groq", "chunk_seconds": 300}},
                "output": {"max_segment_seconds": 300},
            },
            transcriber,
            language=None,
            verbose=False,
        )

    transcriber.transcribe.assert_not_called()
    mock_split_audio.assert_not_called()


@patch("yt2notion.audio.split_audio")
def test_transcribe_full_audio_chunk_mode_enforces_byte_budget_per_chunk(
    mock_split_audio,
    mock_meta,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_full_audio_entries

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"x" * 1000)
    mock_meta.duration_seconds = 120

    oversized_chunk = tmp_path / "chunk_001.mp3"
    oversized_chunk.write_bytes(b"x" * 250)
    ok_chunk = tmp_path / "chunk_002.mp3"
    ok_chunk.write_bytes(b"x" * 80)
    ok_chunk_2 = tmp_path / "chunk_003.mp3"
    ok_chunk_2.write_bytes(b"x" * 80)
    ok_chunk_3 = tmp_path / "chunk_004.mp3"
    ok_chunk_3.write_bytes(b"x" * 80)
    mock_split_audio.return_value = [oversized_chunk, ok_chunk, ok_chunk_2, ok_chunk_3]

    transcriber = MagicMock()
    transcriber.max_upload_bytes = 200
    transcriber.transcribe.side_effect = AssertionError(
        "must not transcribe oversized generated chunk directly"
    )

    with pytest.raises(TranscriptionError, match="minimum chunk size"):
        _transcribe_full_audio_entries(
            audio_path,
            mock_meta,
            {
                "extract": {"asr": {"backend": "groq", "chunk_seconds": 300}},
                "output": {"max_segment_seconds": 300},
            },
            transcriber,
            language=None,
            verbose=False,
        )

    transcriber.transcribe.assert_not_called()


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_transcriber")
@patch("yt2notion.segment._split_by_duration")
def test_transcribe_from_audio_subdivides_oversized_segment_files_by_byte_budget(
    mock_split_by_duration,
    mock_create_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_from_audio
    from yt2notion.workspace import Workspace

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake audio")

    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 120

    oversized_file = tmp_path / "segment_001.mp3"
    oversized_file.write_bytes(b"x" * 180)
    child_1 = tmp_path / "segment_001_child_1.mp3"
    child_2 = tmp_path / "segment_001_child_2.mp3"
    child_1.write_bytes(b"x" * 90)
    child_2.write_bytes(b"x" * 90)

    mock_split_audio.side_effect = [[oversized_file], [child_1, child_2]]

    transcriber = MagicMock()
    transcriber.max_upload_bytes = 100

    def _transcribe_side_effect(path: Path, *, language: str | None = None):
        if path == child_1:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=2.0, text="child one")]
        if path == child_2:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=2.0, text="child two")]
        raise AssertionError(f"unexpected transcription input: {path}")

    transcriber.transcribe.side_effect = _transcribe_side_effect
    mock_create_transcriber.return_value = transcriber
    mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
        Segment(
            title="Part 1",
            start_seconds=int(entries[0].start_seconds),
            end_seconds=int(entries[-1].end_seconds),
            text=" | ".join(entry.text for entry in entries),
        )
    ]

    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)

    result = _transcribe_from_audio(
        audio_path,
        [{"title": "Long segment", "start_seconds": 100, "end_seconds": 220}],
        mock_meta,
        {
            "extract": {"asr": {"backend": "groq", "chunk_seconds": 300}},
            "output": {"max_segment_seconds": 300},
        },
        workspace,
        verbose=False,
    )

    assert mock_split_audio.call_count == 2
    assert transcriber.transcribe.call_count == 2
    assert [call.args[0] for call in transcriber.transcribe.call_args_list] == [child_1, child_2]
    assert result[0]["text"] == "child one child two"


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_transcriber")
@patch("yt2notion.pipeline._rebase_chunk_entries")
def test_transcribe_from_audio_segmented_legacy_path_keeps_direct_transcribe_behavior(
    mock_rebase_chunk_entries,
    mock_create_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_from_audio
    from yt2notion.workspace import Workspace

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake audio")
    segment_file = tmp_path / "segment_001.mp3"
    segment_file.write_bytes(b"fake segment")
    mock_split_audio.return_value = [segment_file]

    transcriber = MagicMock()
    transcriber.max_upload_bytes = None
    transcriber.transcribe.return_value = [
        SubtitleEntry(start_seconds=0.0, end_seconds=0.4, text="drop-if-rebased"),
        SubtitleEntry(start_seconds=1.0, end_seconds=3.0, text="keep"),
    ]
    mock_create_transcriber.return_value = transcriber
    mock_rebase_chunk_entries.side_effect = AssertionError("legacy path should not rebase")

    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    result = _transcribe_from_audio(
        audio_path,
        [{"title": "Part 1", "start_seconds": 100, "end_seconds": 130}],
        mock_meta,
        {
            "extract": {"asr": {"backend": "remote"}},
            "output": {"max_segment_seconds": 300},
        },
        workspace,
        verbose=False,
    )

    assert result[0]["text"] == "drop-if-rebased keep"
    assert transcriber.transcribe.call_count == 1
    mock_rebase_chunk_entries.assert_not_called()


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_transcriber")
def test_transcribe_from_audio_raises_when_min_chunk_still_exceeds_upload_budget(
    mock_create_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _transcribe_from_audio
    from yt2notion.workspace import Workspace

    audio_path = tmp_path / "episode.mp3"
    audio_path.write_bytes(b"fake audio")

    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 120

    oversized_parent = tmp_path / "segment_001.mp3"
    oversized_parent.write_bytes(b"x" * 200)
    oversized_child_floor = tmp_path / "segment_001_child_floor.mp3"
    oversized_child_floor.write_bytes(b"x" * 150)
    child_small = tmp_path / "segment_001_child_small.mp3"
    child_small.write_bytes(b"x" * 10)

    mock_split_audio.side_effect = [[oversized_parent], [oversized_child_floor, child_small]]

    transcriber = MagicMock()
    transcriber.max_upload_bytes = 100
    transcriber.transcribe.side_effect = AssertionError("should not transcribe oversized 30s child")
    mock_create_transcriber.return_value = transcriber

    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)

    with pytest.raises(TranscriptionError, match="minimum chunk size"):
        _transcribe_from_audio(
            audio_path,
            [{"title": "Long segment", "start_seconds": 100, "end_seconds": 140}],
            mock_meta,
            {
                "extract": {"asr": {"backend": "groq", "chunk_seconds": 300}},
                "output": {"max_segment_seconds": 300},
            },
            workspace,
            verbose=False,
        )

    assert mock_split_audio.call_count == 2
    assert transcriber.transcribe.call_count == 0


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


def test_resolve_output_mode_prefers_override(config):
    from yt2notion.pipeline import _resolve_output_mode

    config.output["mode"] = "full"

    assert _resolve_output_mode(config, None) == "full"
    assert _resolve_output_mode(config, "summary") == "summary"


def test_resolve_output_mode_rejects_invalid(config):
    from yt2notion.pipeline import _resolve_output_mode

    with pytest.raises(ValueError, match="Unknown output mode"):
        _resolve_output_mode(config, "invalid-mode")


def test_resolve_note_mode_defaults_to_single_for_non_obsidian(config):
    from yt2notion.pipeline import _resolve_note_mode

    config.output.pop("note_mode", None)

    assert _resolve_note_mode(config) == "single"


def test_resolve_note_mode_defaults_to_source_ab_bundle_for_obsidian(config):
    from yt2notion.pipeline import _resolve_note_mode

    config.storage["backend"] = "obsidian"
    config.output.pop("note_mode", None)

    assert _resolve_note_mode(config) == "source_ab_bundle"


def test_prepare_content_resume_summarize_requires_entities(config, mock_meta):
    from pathlib import Path

    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    workspace.save_metadata(mock_meta)
    workspace.save_segments([])
    workspace.save_transcripts([])

    with pytest.raises(ValueError, match="no entities.json"):
        prepare_content(
            mock_meta.url,
            config,
            resume_from="summarize",
            workspace_dir=str(workspace.dir),
        )


@patch("yt2notion.pipeline.create_llm_caller")
def test_step_extract_skips_large_subtitle_derived_input(mock_create_llm_caller):
    from yt2notion.pipeline import ENTITY_EXTRACT_SUBTITLE_SKIP_THRESHOLD, _step_extract

    segments = [
        {
            "title": f"Part {i}",
            "start_seconds": i * 10,
            "end_seconds": (i + 1) * 10,
            "text": "subtitle text",
            "source": "subtitle",
        }
        for i in range(ENTITY_EXTRACT_SUBTITLE_SKIP_THRESHOLD + 1)
    ]

    result = _step_extract(segments, {"model": {"backend": "codex_cli"}}, verbose=False)

    assert result.entities == []
    mock_create_llm_caller.assert_not_called()


@patch("yt2notion.entity_extract.extract_entities")
@patch("yt2notion.pipeline.create_llm_caller")
def test_step_extract_runs_for_asr_segments(mock_create_llm_caller, mock_extract_entities):
    from yt2notion.models.base import EntityResult
    from yt2notion.pipeline import _step_extract

    caller = MagicMock()
    mock_create_llm_caller.return_value = caller
    expected = EntityResult(
        domain="General",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )
    mock_extract_entities.return_value = expected

    segments = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 60,
            "text": "asr text",
            "source": "asr",
        }
    ]

    result = _step_extract(segments, {"model": {"backend": "codex_cli"}}, verbose=False)

    assert result == expected
    mock_create_llm_caller.assert_called_once()
    mock_extract_entities.assert_called_once()


@patch("yt2notion.pipeline.prepare_content")
@patch("yt2notion.pipeline.create_storage")
def test_run_pipeline_long_full_adds_transcript_subpage(
    mock_create_storage,
    mock_prepare_content,
    config,
):
    from pathlib import Path

    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    workspace = Workspace(Path(config.workspace["base_dir"]), "abc123")
    transcript_segments = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 30,
            "text": "reviewed long transcript",
            "source": "asr",
        }
    ]
    metadata = VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
    )
    mock_prepare_content.return_value = PreparedContent(
        metadata=metadata,
        chinese_content=ChineseContent(
            overview="测试概要",
            key_points=[],
            tags=[],
            raw_markdown="## 概要\n\n测试概要",
        ),
        transcript_segments=transcript_segments,
        entities=None,
        workspace=workspace,
        is_long=True,
        output_mode="full",
    )

    mock_storage = MagicMock()
    mock_storage.save.return_value = "https://notion.so/page123"
    mock_create_storage.return_value = mock_storage

    result = run_pipeline("https://example.com/video", config, mode="full")

    assert result == "https://notion.so/page123"
    save_kwargs = mock_storage.save.call_args.kwargs
    assert save_kwargs["transcript_segments"] is None
    mock_storage.add_transcript_subpage.assert_called_once_with(
        "https://notion.so/page123", transcript_segments, metadata
    )


@patch("yt2notion.pipeline._step_summarize")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_clears_stale_asr_fallback_marker_when_transcribe_runs_fresh(
    mock_step_download,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_summarize,
    mock_meta,
    mock_chinese,
    config,
):
    from pathlib import Path

    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    mock_meta.subtitles_available = False
    mock_step_download.return_value = mock_meta
    mock_download_audio.return_value = None
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 20,
            "text": "subtitle-like text",
            "source": "subtitle",
        }
    ]
    mock_step_summarize.return_value = mock_chinese

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.mark_asr_fallback_used()
    assert ws.asr_fallback_used() is True

    prepared = prepare_content("https://example.com/video", config, mode="summary")

    assert prepared.workspace.asr_fallback_used() is False


@patch("yt2notion.pipeline._step_summarize")
def test_prepare_content_resume_after_transcribe_preserves_fallback_marker(
    mock_step_summarize,
    mock_meta,
    mock_chinese,
    config,
):
    from pathlib import Path

    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.save_metadata(mock_meta)
    ws.save_segments([])
    ws.save_transcripts(
        [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 20,
                "text": "subtitle-like text",
                "source": "subtitle",
            }
        ]
    )
    ws.mark_asr_fallback_used()
    assert ws.asr_fallback_used() is True

    mock_step_summarize.return_value = mock_chinese
    prepared = prepare_content(
        mock_meta.url,
        config,
        mode="summary",
        resume_from="review",
        workspace_dir=str(ws.dir),
    )

    assert prepared.workspace.asr_fallback_used() is True
