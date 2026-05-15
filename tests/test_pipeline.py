"""Tests for pipeline orchestrator."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from yt2notion.config import AppConfig
from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta
from yt2notion.process import SubtitleEntry
from yt2notion.segment import Segment
from yt2notion.transcribe.errors import (
    TranscriptionDailyLimitError,
    TranscriptionError,
    TranscriptionHourlyLimitError,
)


@pytest.fixture
def mock_meta():
    return VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://www.youtube.com/watch?v=abc123",
        upload_date="20260319",
        duration_seconds=600,
        subtitles_available=False,
    )


@pytest.fixture
def config(tmp_path):
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path / "workspace")}
    return cfg


@pytest.fixture
def note_bundle():
    return NoteBundle(
        source=NoteDocument(
            title="Test Video",
            markdown="# Source",
            tags=["test"],
            variant="source",
        ),
        guide=NoteDocument(
            title="Test Video - A 导读",
            markdown="# Guide",
            tags=["test", "guide"],
            variant="a_guide",
        ),
        longform=NoteDocument(
            title="Test Video - B 扩展",
            markdown="# Longform",
            tags=["test", "longform"],
            variant="b_longform",
        ),
        stable_tags=["test"],
        source_topics=["topic"],
    )


def _minimal_transcript(source: str, text: str = "raw text") -> list[dict]:
    return [
        {
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 60,
            "text": text,
            "source": source,
        }
    ]


def test_step_segment_uses_description_timestamp_outline(config):
    from yt2notion.pipeline import _step_segment

    metadata = VideoMeta(
        video_id="outline123",
        title="Outlined Episode",
        channel="TestChannel",
        duration_seconds=1800,
        description=(
            "00:00 Opening\n"
            "12:30 Training plan\n"
            "28:10 Diet notes\n"
        ),
    )

    segments = _step_segment(metadata, {"output": {"max_segment_seconds": 1000}}, verbose=False)

    assert segments == [
        {"title": "Opening", "start_seconds": 0, "end_seconds": 750},
        {"title": "Training plan", "start_seconds": 750, "end_seconds": 1690},
        {"title": "Diet notes", "start_seconds": 1690, "end_seconds": 1800},
    ]


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.segment_transcript")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_manual_subtitle_skips_cleanup(
    mock_step_download,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_review,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_segment_transcript,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content

    transcripts = _minimal_transcript("manual_subtitle", "manual transcript")
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = transcripts
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    prepared = prepare_content(mock_meta.url, config, mode="summary")

    assert prepared.note_bundle == note_bundle
    mock_step_review.assert_not_called()
    mock_segment_transcript.assert_not_called()
    assert prepared.workspace.load_reviewed() is None
    mock_build_note_bundle.assert_called_once_with(
        transcripts, mock_meta, mock_create_summarizer.return_value
    )


@pytest.mark.parametrize("source", ["auto_caption", "webpage_transcript", "asr", "subtitle"])
@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline.segment_transcript")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_asr_like_sources_are_cleaned(
    mock_step_download,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_review,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_segment_transcript,
    mock_create_summarizer,
    mock_build_note_bundle,
    source,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content

    transcripts = _minimal_transcript(source, "raw transcript")
    reviewed = _minimal_transcript(source, "cleaned transcript")
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = transcripts
    mock_segment_transcript.side_effect = lambda segments, *_args, **_kwargs: segments
    mock_step_review.return_value = reviewed
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    prepared = prepare_content(mock_meta.url, config, mode="summary")

    assert prepared.note_bundle == note_bundle
    mock_segment_transcript.assert_called_once()
    mock_step_review.assert_called_once()
    assert prepared.workspace.load_reviewed() == reviewed
    mock_build_note_bundle.assert_called_once_with(
        reviewed, mock_meta, mock_create_summarizer.return_value
    )


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_review")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_always_writes_note_bundle_not_legacy_artifacts(
    mock_step_download,
    mock_step_segment,
    mock_step_transcribe,
    mock_step_review,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content

    transcripts = _minimal_transcript("asr")
    reviewed = _minimal_transcript("asr", "cleaned")
    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = transcripts
    mock_step_review.return_value = reviewed
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    prepared = prepare_content(mock_meta.url, config)

    assert prepared.note_bundle == note_bundle
    assert (prepared.workspace.dir / "note_bundle.json").exists()
    assert not (prepared.workspace.dir / "summary.json").exists()
    assert not (prepared.workspace.dir / "entities.json").exists()


def test_prepare_content_rejects_full_mode(config):
    from yt2notion.pipeline import prepare_content

    with pytest.raises(ValueError, match="supports summary mode only"):
        prepare_content("https://example.com/video", config, mode="full")


@patch("yt2notion.pipeline.prepare_content")
@patch("yt2notion.pipeline.create_storage")
def test_run_pipeline_publishes_note_bundle_to_obsidian(
    mock_create_storage,
    mock_prepare_content,
    config,
    mock_meta,
    note_bundle,
):
    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    config.storage["backend"] = "obsidian"
    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    mock_prepare_content.return_value = PreparedContent(
        metadata=mock_meta,
        note_bundle=note_bundle,
        workspace=workspace,
        is_long=False,
    )
    storage = MagicMock()
    storage.save_note_bundle.return_value = "obsidian://Test Video"
    mock_create_storage.return_value = storage

    result = run_pipeline(mock_meta.url, config)

    assert result == "obsidian://Test Video"
    storage.save_note_bundle.assert_called_once_with(note_bundle, mock_meta)


@patch("yt2notion.pipeline.prepare_content")
def test_run_pipeline_rejects_non_obsidian_publish_backend(mock_prepare_content, config):
    from yt2notion.pipeline import run_pipeline

    config.storage["backend"] = "notion"

    with pytest.raises(ValueError, match="requires obsidian backend"):
        run_pipeline("https://example.com/video", config)

    mock_prepare_content.assert_not_called()


@patch("yt2notion.pipeline.prepare_content")
def test_run_pipeline_dry_run_allows_non_obsidian_backend(
    mock_prepare_content,
    config,
    mock_meta,
    note_bundle,
):
    from yt2notion.pipeline import PreparedContent, run_pipeline
    from yt2notion.workspace import Workspace

    config.storage["backend"] = "notion"
    workspace = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    mock_prepare_content.return_value = PreparedContent(
        metadata=mock_meta,
        note_bundle=note_bundle,
        workspace=workspace,
        is_long=False,
    )

    output = run_pipeline("https://example.com/video", config, dry_run=True)

    assert "# Source" in output
    assert "# A / Guide" in output
    assert "# B / Longform" in output


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_records_summarize_failure(
    mock_step_download,
    mock_step_segment,
    mock_step_transcribe,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
):
    from yt2notion.pipeline import prepare_content

    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = _minimal_transcript("manual_subtitle")
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.side_effect = RuntimeError("summary crashed")

    with pytest.raises(RuntimeError, match="summary crashed"):
        prepare_content(mock_meta.url, config)

    failed_file = Path(config.workspace["base_dir"]) / mock_meta.video_id / "failed.json"
    assert failed_file.exists()
    data = failed_file.read_text(encoding="utf-8")
    assert '"step": "summarize"' in data
    assert '"retries_exhausted": false' in data.lower()


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._download_webpage_transcript")
@patch("yt2notion.pipeline._download_audio")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
@patch("yt2notion.pipeline._step_download")
def test_prepare_content_clears_stale_asr_fallback_marker_when_transcribe_runs_fresh(
    mock_step_download,
    mock_step_segment,
    mock_step_transcribe,
    mock_download_audio,
    mock_download_webpage_transcript,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    mock_step_download.return_value = mock_meta
    mock_download_webpage_transcript.return_value = False
    mock_step_segment.return_value = []
    mock_step_transcribe.return_value = _minimal_transcript("manual_subtitle")
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.mark_asr_fallback_used()
    assert ws.asr_fallback_used() is True

    prepared = prepare_content(mock_meta.url, config, mode="summary")

    assert prepared.workspace.asr_fallback_used() is False


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._step_transcribe")
@patch("yt2notion.pipeline._step_segment")
def test_prepare_content_resume_from_segment_clears_stale_transcribe_checkpoint_artifacts(
    mock_step_segment,
    mock_step_transcribe,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.save_metadata(mock_meta)
    ws.save_segments(
        [{"title": "Old Part 1", "start_seconds": 0.0, "end_seconds": 60.0, "text": ""}]
    )
    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "segment-001",
                "segment_index": 0,
                "title": "Old Part 1",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "audio_relpath": "segments/segment_001.mp3",
                "preferred_backend": "remote",
            }
        ]
    )
    ws.save_transcribe_state(
        {
            "version": 1,
            "job_mode": "remote_remaining",
            "status": "running",
            "next_attempt_at": None,
            "last_error": None,
            "defer_reason": None,
            "ash_defer_count": 0,
            "chunks": [
                {
                    "chunk_id": "segment-001",
                    "status": "completed_remote",
                    "backend_used": "remote",
                    "result_relpath": "transcribe_chunks/segment-001.json",
                    "attempts": 1,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                }
            ],
        }
    )
    ws.save_transcribe_chunk_result(
        "segment-001",
        [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "stale text", "source": "asr"}],
    )
    ws.mark_asr_fallback_used()

    mock_step_segment.return_value = [
        {"title": "New Part 1", "start_seconds": 0.0, "end_seconds": 120.0}
    ]

    def _assert_clean_checkpoint_state(*args, **kwargs):
        step_ws = args[0]
        assert step_ws.load_transcribe_plan() is None
        assert step_ws.load_transcribe_state() is None
        assert step_ws.load_transcribe_chunk_result("segment-001") is None
        return _minimal_transcript("manual_subtitle", "fresh text")

    mock_step_transcribe.side_effect = _assert_clean_checkpoint_state
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    prepare_content(
        mock_meta.url,
        config,
        mode="summary",
        resume_from="segment",
        workspace_dir=str(ws.dir),
    )


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
def test_prepare_content_resume_after_transcribe_preserves_fallback_marker(
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.save_metadata(mock_meta)
    ws.save_segments([])
    ws.save_transcripts(_minimal_transcript("manual_subtitle"))
    ws.mark_asr_fallback_used()
    assert ws.asr_fallback_used() is True

    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle
    prepared = prepare_content(
        mock_meta.url,
        config,
        mode="summary",
        resume_from="review",
        workspace_dir=str(ws.dir),
    )

    assert prepared.workspace.asr_fallback_used() is True


@patch("yt2notion.pipeline.build_note_bundle")
@patch("yt2notion.pipeline.create_summarizer")
@patch("yt2notion.pipeline._step_transcribe")
def test_prepare_content_resume_from_transcribe_preserves_fallback_marker(
    mock_step_transcribe,
    mock_create_summarizer,
    mock_build_note_bundle,
    mock_meta,
    config,
    note_bundle,
):
    from yt2notion.pipeline import prepare_content
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    ws.save_metadata(mock_meta)
    ws.save_segments([])
    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "audio_relpath": "audio.mp3",
                "preferred_backend": "remote",
            }
        ]
    )
    ws.save_transcribe_state(
        {
            "version": 1,
            "job_mode": "remote_remaining",
            "status": "running",
            "next_attempt_at": None,
            "last_error": None,
            "defer_reason": None,
            "ash_defer_count": 0,
            "chunks": [
                {
                    "chunk_id": "chunk-001",
                    "status": "pending",
                    "backend_used": None,
                    "result_relpath": None,
                    "attempts": 0,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                }
            ],
        }
    )
    ws.mark_asr_fallback_used()
    assert ws.asr_fallback_used() is True

    mock_step_transcribe.return_value = _minimal_transcript("manual_subtitle", "transcribed text")
    mock_create_summarizer.return_value = MagicMock()
    mock_build_note_bundle.return_value = note_bundle

    prepared = prepare_content(
        mock_meta.url,
        config,
        mode="summary",
        resume_from="transcribe",
        workspace_dir=str(ws.dir),
    )

    assert prepared.workspace.asr_fallback_used() is True


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




def test_step_transcribe_preserves_saved_subtitle_source(tmp_path, mock_meta):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(tmp_path, mock_meta.video_id)
    srt = tmp_path / "source.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nManual line\n")
    ws.save_subtitles(srt)
    ws.save_subtitle_source("manual_subtitle")

    transcripts = _step_transcribe(ws, mock_meta, [], {"output": {}}, verbose=False)

    assert transcripts[0]["source"] == "manual_subtitle"


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


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.pipeline._now")
@patch("yt2notion.pipeline.time.sleep")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_waits_and_retries_hourly_groq_limit(
    mock_create_transcriber,
    mock_sleep,
    mock_now,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    progress_events: list[tuple[str, str, str | None]] = []
    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)
    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 120

    chunk_1 = ws.dir / "full_audio_chunks" / "chunk_001.mp3"
    chunk_2 = ws.dir / "full_audio_chunks" / "chunk_002.mp3"
    chunk_1.parent.mkdir(parents=True, exist_ok=True)
    chunk_1.write_bytes(b"chunk-1")
    chunk_2.write_bytes(b"chunk-2")
    mock_split_audio.return_value = [chunk_1, chunk_2]

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.side_effect = [
        TranscriptionHourlyLimitError("hourly", retry_after_seconds=120),
        [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk one")],
        [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk two")],
    ]
    mock_create_transcriber.return_value = primary
    start = datetime(2026, 4, 19, 12, 0, tzinfo=UTC)
    mock_now.side_effect = [
        start,
        start,
        start,
        start + timedelta(seconds=60),
        start + timedelta(seconds=120),
        start + timedelta(seconds=121),
        start + timedelta(seconds=122),
        start + timedelta(seconds=123),
        start + timedelta(seconds=124),
        start + timedelta(seconds=125),
    ]

    with patch("yt2notion.segment._split_by_duration") as mock_split_by_duration:
        mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
            Segment(
                title="Part 1",
                start_seconds=int(entries[0].start_seconds),
                end_seconds=int(entries[-1].end_seconds),
                text=" ".join(entry.text for entry in entries),
            )
        ]

        result = _step_transcribe(
            ws,
            mock_meta,
            [],
            {"extract": {"asr": {"backend": "groq", "chunk_seconds": 60}}},
            verbose=False,
            progress_callback=lambda step, event, message=None: progress_events.append(
                (step, event, message)
            ),
        )

    assert result[0]["text"] == "chunk one chunk two"
    assert primary.transcribe.call_count == 3
    sleep_calls = [call.args[0] for call in mock_sleep.call_args_list]
    assert sleep_calls
    assert all(call <= 60 for call in sleep_calls)
    assert ws.asr_fallback_used() is False
    assert ws.load_transcripts() is None
    state = ws.load_transcribe_state()
    assert state is not None
    assert state["status"] == "completed"
    assert state["ash_defer_count"] == 1
    assert state["next_attempt_at"] is None
    assert [chunk["status"] for chunk in state["chunks"]] == ["completed_groq", "completed_groq"]
    assert ws.load_transcribe_plan() is not None
    assert ws.load_transcribe_chunk_result("chunk-001")[0]["text"] == "chunk one"
    assert ws.load_transcribe_chunk_result("chunk-002")[0]["text"] == "chunk two"
    assert [event for _, event, _ in progress_events].count("chunk_started") == 3
    assert [event for _, event, _ in progress_events].count("hourly_wait") == 1
    assert [event for _, event, _ in progress_events].count("chunk_completed") == 2
    hourly_wait_payload = next(
        json.loads(message)
        for step, event, message in progress_events
        if step == "transcribe" and event == "hourly_wait" and message is not None
    )
    assert hourly_wait_payload["chunk_id"] == "chunk-001"
    assert hourly_wait_payload["backend"] == "groq"
    assert hourly_wait_payload["retry_after_seconds"] == 120
    chunk_completed_payload = next(
        json.loads(message)
        for step, event, message in progress_events
        if step == "transcribe" and event == "chunk_completed" and message is not None
    )
    assert chunk_completed_payload["chunk_id"] == "chunk-001"
    assert chunk_completed_payload["backend"] == "groq"


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_does_not_fallback_for_non_retryable_transcription_error(
    mock_create_transcriber,
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
    mock_create_transcriber.return_value = primary

    with pytest.raises(TranscriptionError, match="bad request"):
        _step_transcribe(
            ws,
            mock_meta,
            [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
            {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
            verbose=False,
        )

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
def test_step_transcribe_propagates_daily_limit_when_no_fallback_configured(
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
    primary.transcribe.side_effect = TranscriptionDailyLimitError("daily")
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.return_value = None

    with pytest.raises(TranscriptionDailyLimitError, match="daily"):
        _step_transcribe(
            ws,
            mock_meta,
            [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
            {"extract": {"asr": {"backend": "groq"}}},
            verbose=False,
        )

    assert ws.asr_fallback_used() is False


@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.create_fallback_transcriber")
@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_switches_remaining_chunks_to_remote_after_daily_limit(
    mock_create_transcriber,
    mock_create_fallback_transcriber,
    mock_split_audio,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    progress_events: list[tuple[str, str, str | None]] = []
    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    ws.save_audio(source_audio)
    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 180

    chunk_1 = ws.dir / "full_audio_chunks" / "chunk_001.mp3"
    chunk_2 = ws.dir / "full_audio_chunks" / "chunk_002.mp3"
    chunk_3 = ws.dir / "full_audio_chunks" / "chunk_003.mp3"
    chunk_1.parent.mkdir(parents=True, exist_ok=True)
    for path in (chunk_1, chunk_2, chunk_3):
        path.write_bytes(path.name.encode("utf-8"))
    mock_split_audio.return_value = [chunk_1, chunk_2, chunk_3]

    primary = MagicMock()
    primary.max_upload_bytes = None

    def _primary_side_effect(path: Path, *, language: str | None = None):
        if path == chunk_1:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk one")]
        if path == chunk_2:
            raise TranscriptionDailyLimitError("daily")
        raise AssertionError(f"unexpected primary path {path}")

    primary.transcribe.side_effect = _primary_side_effect
    fallback = MagicMock()
    fallback.max_upload_bytes = None

    def _fallback_side_effect(path: Path, *, language: str | None = None):
        if path == chunk_2:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk two")]
        if path == chunk_3:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk three")]
        raise AssertionError(f"unexpected fallback path {path}")

    fallback.transcribe.side_effect = _fallback_side_effect
    mock_create_transcriber.return_value = primary
    mock_create_fallback_transcriber.return_value = fallback

    with patch("yt2notion.segment._split_by_duration") as mock_split_by_duration:
        mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
            Segment(
                title="Part 1",
                start_seconds=int(entries[0].start_seconds),
                end_seconds=int(entries[-1].end_seconds),
                text=" ".join(entry.text for entry in entries),
            )
        ]

        result = _step_transcribe(
            ws,
            mock_meta,
            [],
            {
                "extract": {
                    "asr": {
                        "backend": "groq",
                        "fallback_backend": "remote",
                        "chunk_seconds": 60,
                    }
                }
            },
            verbose=False,
            progress_callback=lambda step, event, message=None: progress_events.append(
                (step, event, message)
            ),
        )

    assert result[0]["text"] == "chunk one chunk two chunk three"
    assert ws.asr_fallback_used() is True
    assert primary.transcribe.call_count == 2
    assert fallback.transcribe.call_count == 2
    assert ws.load_transcripts() is None
    state = ws.load_transcribe_state()
    assert state is not None
    assert state["status"] == "completed"
    assert state["job_mode"] == "remote_remaining"
    assert [chunk["status"] for chunk in state["chunks"]] == [
        "completed_groq",
        "completed_remote",
        "completed_remote",
    ]
    assert [chunk["backend_used"] for chunk in state["chunks"]] == ["groq", "remote", "remote"]
    plan = ws.load_transcribe_plan()
    assert plan is not None
    assert [chunk["preferred_backend"] for chunk in plan] == ["groq", "remote", "remote"]
    assert [event for _, event, _ in progress_events].count("daily_fallback_switch") == 1
    switch_payload = next(
        json.loads(message)
        for step, event, message in progress_events
        if step == "transcribe" and event == "daily_fallback_switch" and message is not None
    )
    assert switch_payload["chunk_id"] == "chunk-002"
    assert switch_payload["backend"] == "groq"
    assert switch_payload["fallback_backend"] == "remote"
    assert switch_payload["affected_chunk_ids"] == ["chunk-002", "chunk-003"]
    remote_completions = [
        json.loads(message)
        for step, event, message in progress_events
        if step == "transcribe" and event == "chunk_completed" and message is not None
    ]
    assert [payload["backend"] for payload in remote_completions] == [
        "groq",
        "remote",
        "remote",
    ]


@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_resumes_from_existing_chunk_files(
    mock_create_transcriber,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    saved_audio = ws.save_audio(source_audio)
    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 120

    chunk_1 = ws.dir / "full_audio_chunks" / "chunk_001.mp3"
    chunk_2 = ws.dir / "full_audio_chunks" / "chunk_002.mp3"
    chunk_1.parent.mkdir(parents=True, exist_ok=True)
    chunk_1.write_bytes(b"chunk-1")
    chunk_2.write_bytes(b"chunk-2")

    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "audio_relpath": str(chunk_1.relative_to(ws.dir)),
                "preferred_backend": "groq",
            },
            {
                "chunk_id": "chunk-002",
                "title": "Chunk 2",
                "start_seconds": 60.0,
                "end_seconds": 120.0,
                "audio_relpath": str(chunk_2.relative_to(ws.dir)),
                "preferred_backend": "groq",
            },
        ]
    )
    ws.save_transcribe_state(
        {
            "version": 1,
            "job_mode": "groq",
            "status": "running",
            "next_attempt_at": None,
            "last_error": None,
            "defer_reason": None,
            "ash_defer_count": 0,
            "chunks": [
                {
                    "chunk_id": "chunk-001",
                    "status": "pending",
                    "backend_used": None,
                    "result_relpath": None,
                    "attempts": 0,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                },
                {
                    "chunk_id": "chunk-002",
                    "status": "pending",
                    "backend_used": None,
                    "result_relpath": None,
                    "attempts": 0,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                },
            ],
        }
    )
    ws.save_transcribe_chunk_result(
        "chunk-001",
        [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "chunk one", "source": "asr"}],
    )

    primary = MagicMock()
    primary.max_upload_bytes = None

    def _primary_side_effect(path: Path, *, language: str | None = None):
        if path == saved_audio:
            raise AssertionError("should not retry direct full-audio upload when plan exists")
        if path == chunk_2:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="chunk two")]
        raise AssertionError(f"unexpected path {path}")

    primary.transcribe.side_effect = _primary_side_effect
    mock_create_transcriber.return_value = primary

    with patch("yt2notion.segment._split_by_duration") as mock_split_by_duration:
        mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
            Segment(
                title="Part 1",
                start_seconds=int(entries[0].start_seconds),
                end_seconds=int(entries[-1].end_seconds),
                text=" ".join(entry.text for entry in entries),
            )
        ]

        result = _step_transcribe(
            ws,
            mock_meta,
            [],
            {"extract": {"asr": {"backend": "groq", "chunk_seconds": 60}}},
            verbose=False,
        )

    assert result[0]["text"] == "chunk one chunk two"
    primary.transcribe.assert_called_once_with(chunk_2, language=None)
    state = ws.load_transcribe_state()
    assert state is not None
    assert [chunk["status"] for chunk in state["chunks"]] == ["completed_groq", "completed_groq"]


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



@patch("yt2notion.transcribe.create_transcriber")
def test_step_transcribe_reruns_completed_chunk_when_chunk_payload_is_missing(
    mock_create_transcriber,
    mock_meta,
    config,
    tmp_path,
):
    from yt2notion.pipeline import _step_transcribe
    from yt2notion.workspace import Workspace

    ws = Workspace(Path(config.workspace["base_dir"]), mock_meta.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    saved_audio = ws.save_audio(source_audio)
    mock_meta.subtitles_available = False
    mock_meta.duration_seconds = 60

    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": 60.0,
                "audio_relpath": str(saved_audio.relative_to(ws.dir)),
                "preferred_backend": "groq",
            }
        ]
    )
    ws.save_transcribe_state(
        {
            "version": 1,
            "job_mode": "groq",
            "status": "running",
            "next_attempt_at": None,
            "last_error": None,
            "defer_reason": None,
            "ash_defer_count": 0,
            "chunks": [
                {
                    "chunk_id": "chunk-001",
                    "status": "completed_groq",
                    "backend_used": "groq",
                    "result_relpath": "transcribe_chunks/chunk-001.json",
                    "attempts": 1,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                }
            ],
        }
    )

    primary = MagicMock()
    primary.max_upload_bytes = None
    primary.transcribe.return_value = [
        SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="recovered text")
    ]
    mock_create_transcriber.return_value = primary

    with patch("yt2notion.segment._split_by_duration") as mock_split_by_duration:
        mock_split_by_duration.side_effect = lambda entries, _max_seconds: [
            Segment(
                title="Part 1",
                start_seconds=int(entries[0].start_seconds),
                end_seconds=int(entries[-1].end_seconds),
                text=" ".join(entry.text for entry in entries),
            )
        ]

        result = _step_transcribe(
            ws,
            mock_meta,
            [],
            {"extract": {"asr": {"backend": "groq", "chunk_seconds": 60}}},
            verbose=False,
        )

    assert result[0]["text"] == "recovered text"
    primary.transcribe.assert_called_once_with(saved_audio, language=None)
    assert ws.load_transcribe_chunk_result("chunk-001")[0]["text"] == "recovered text"
