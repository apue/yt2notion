"""Contract and state-machine tests for the transcription engine."""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from yt2notion.process import SubtitleEntry
from yt2notion.segment import Segment
from yt2notion.transcribe.engine import TranscriptionEngine
from yt2notion.transcribe.errors import (
    TranscriptionDailyLimitError,
    TranscriptionError,
    TranscriptionHourlyLimitError,
)
from yt2notion.workspace import Workspace

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta


def _segment_result(entries: list[SubtitleEntry], _max_seconds: int) -> list[Segment]:
    return [
        Segment(
            title="Part 1",
            start_seconds=int(entries[0].start_seconds),
            end_seconds=int(entries[-1].end_seconds),
            text=" ".join(entry.text for entry in entries),
        )
    ]


def _audio_workspace(tmp_path: Path, metadata: VideoMeta) -> tuple[Workspace, Path]:
    workspace = Workspace(tmp_path / "workspace", metadata.video_id)
    source_audio = tmp_path / "episode.mp3"
    source_audio.write_bytes(b"fake audio")
    return workspace, workspace.save_audio(source_audio)


def _chunk_files(workspace: Workspace, count: int) -> list[Path]:
    paths = [
        workspace.dir / "full_audio_chunks" / f"chunk_{index:03d}.mp3"
        for index in range(1, count + 1)
    ]
    paths[0].parent.mkdir(parents=True, exist_ok=True)
    for path in paths:
        path.write_bytes(path.name.encode())
    return paths


def test_transcribe_workspace_preserves_saved_subtitle_source(
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace = Workspace(tmp_path, metadata.video_id)
    subtitle = tmp_path / "source.srt"
    subtitle.write_text("1\n00:00:01,000 --> 00:00:02,000\nManual line\n")
    workspace.save_subtitles(subtitle)
    workspace.save_subtitle_source("manual_subtitle")
    engine = TranscriptionEngine({"output": {}})

    transcripts = engine.transcribe_workspace(workspace, metadata, [])

    assert transcripts[0]["source"] == "manual_subtitle"


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
@patch("yt2notion.audio.split_audio")
@patch("yt2notion.transcribe.engine.time.sleep", return_value=None)
def test_hourly_limit_retries_same_chunk_and_records_checkpoint(
    _sleep: MagicMock,
    split_audio: MagicMock,
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    chunks = _chunk_files(workspace, 2)
    split_audio.return_value = chunks
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.side_effect = [
        TranscriptionHourlyLimitError("hourly", retry_after_seconds=0),
        [SubtitleEntry(0.0, 1.0, "chunk one")],
        [SubtitleEntry(0.0, 1.0, "chunk two")],
    ]
    events: list[tuple[str, str, str | None]] = []
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 60}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    result = engine.transcribe_audio(
        audio_path,
        [],
        metadata,
        workspace,
        progress_callback=lambda step, event, message=None: events.append((step, event, message)),
    )

    assert result[0]["text"] == "chunk one chunk two"
    assert primary.transcribe.call_count == 3
    state = workspace.load_transcribe_state()
    assert state is not None
    assert state["status"] == "completed"
    assert state["ash_defer_count"] == 1
    assert [chunk["status"] for chunk in state["chunks"]] == [
        "completed_groq",
        "completed_groq",
    ]
    wait_event = next(message for _, event, message in events if event == "hourly_wait")
    assert wait_event is not None
    assert json.loads(wait_event)["chunk_id"] == "chunk-001"


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
@patch("yt2notion.audio.split_audio")
def test_daily_limit_switches_current_and_remaining_chunks_to_fallback(
    split_audio: MagicMock,
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    metadata.duration_seconds = 180
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    chunks = _chunk_files(workspace, 3)
    split_audio.return_value = chunks
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.side_effect = [
        [SubtitleEntry(0.0, 1.0, "chunk one")],
        TranscriptionDailyLimitError("daily"),
    ]
    fallback = MagicMock(max_upload_bytes=None)
    fallback.transcribe.side_effect = [
        [SubtitleEntry(0.0, 1.0, "chunk two")],
        [SubtitleEntry(0.0, 1.0, "chunk three")],
    ]
    engine = TranscriptionEngine(
        {
            "extract": {
                "asr": {
                    "backend": "groq",
                    "fallback_backend": "remote",
                    "chunk_seconds": 60,
                }
            }
        },
        primary_transcriber=primary,
        primary_backend="groq",
        fallback_backend="remote",
        fallback_transcriber_factory=lambda: fallback,
    )

    result = engine.transcribe_audio(audio_path, [], metadata, workspace)

    assert result[0]["text"] == "chunk one chunk two chunk three"
    assert workspace.asr_fallback_used() is True
    state = workspace.load_transcribe_state()
    assert state is not None
    assert state["job_mode"] == "remote_remaining"
    assert [chunk["backend_used"] for chunk in state["chunks"]] == [
        "groq",
        "remote",
        "remote",
    ]
    assert primary.transcribe.call_count == 2
    assert fallback.transcribe.call_count == 2


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
def test_resume_reuses_completed_chunk_payload(
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, _audio_path = _audio_workspace(tmp_path, metadata)
    chunks = _chunk_files(workspace, 2)
    workspace.save_transcribe_plan(
        [
            {
                "chunk_id": f"chunk-{index:03d}",
                "title": f"Chunk {index}",
                "start_seconds": float((index - 1) * 60),
                "end_seconds": float(index * 60),
                "audio_relpath": str(path.relative_to(workspace.dir)),
                "preferred_backend": "groq",
            }
            for index, path in enumerate(chunks, start=1)
        ]
    )
    workspace.save_transcribe_state(
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
                    "chunk_id": f"chunk-{index:03d}",
                    "status": "pending",
                    "backend_used": None,
                    "result_relpath": None,
                    "attempts": 0,
                    "updated_at": "2026-04-19T12:00:00+08:00",
                }
                for index in range(1, 3)
            ],
        }
    )
    workspace.save_transcribe_chunk_result(
        "chunk-001",
        [{"start_seconds": 0.0, "end_seconds": 1.0, "text": "cached", "source": "asr"}],
    )
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.return_value = [SubtitleEntry(0.0, 1.0, "fresh")]
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 60}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    result = engine.transcribe_audio(workspace.audio_path, [], metadata, workspace)

    assert result[0]["text"] == "cached fresh"
    primary.transcribe.assert_called_once_with(chunks[1], language=None)


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
def test_missing_completed_chunk_payload_is_recomputed(
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    workspace.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": 120.0,
                "audio_relpath": str(audio_path.relative_to(workspace.dir)),
                "preferred_backend": "groq",
            }
        ]
    )
    workspace.save_transcribe_state(
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
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.return_value = [SubtitleEntry(0.0, 1.0, "recovered")]
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq"}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    result = engine.transcribe_audio(audio_path, [], metadata, workspace)

    assert result[0]["text"] == "recovered"
    primary.transcribe.assert_called_once_with(audio_path, language=None)
    assert workspace.load_transcribe_chunk_result("chunk-001")[0]["text"] == "recovered"


@patch("yt2notion.audio.split_audio")
def test_oversize_short_audio_fails_before_provider_upload(
    split_audio: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    metadata.duration_seconds = 20
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    audio_path.write_bytes(b"x" * 200)
    primary = MagicMock(max_upload_bytes=100)
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 300}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    with pytest.raises(TranscriptionError, match="minimum chunk size"):
        engine.transcribe_audio(audio_path, [], metadata, workspace)

    primary.transcribe.assert_not_called()
    split_audio.assert_not_called()


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
@patch("yt2notion.audio.split_audio")
def test_small_full_audio_uses_single_upload_fast_path(
    split_audio: MagicMock,
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    primary = MagicMock(max_upload_bytes=100)
    primary.transcribe.return_value = [SubtitleEntry(0.0, 1.0, "single request")]
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 300}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    result = engine.transcribe_audio(audio_path, [], metadata, workspace)

    assert result[0]["text"] == "single request"
    primary.transcribe.assert_called_once_with(audio_path, language=None)
    split_audio.assert_not_called()


@patch("yt2notion.audio.split_audio")
def test_non_retryable_error_does_not_load_fallback(
    split_audio: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    segment_file = tmp_path / "segment.mp3"
    segment_file.write_bytes(b"segment")
    split_audio.return_value = [segment_file]
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.side_effect = TranscriptionError("bad request")
    fallback_factory = MagicMock()
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
        primary_transcriber=primary,
        primary_backend="groq",
        fallback_backend="remote",
        fallback_transcriber_factory=fallback_factory,
    )

    with pytest.raises(TranscriptionError, match="bad request"):
        engine.transcribe_audio(
            audio_path,
            [{"title": "Part 1", "start_seconds": 0, "end_seconds": 30}],
            metadata,
            workspace,
        )

    fallback_factory.assert_not_called()
    assert workspace.asr_fallback_used() is False


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
def test_daily_limit_without_fallback_is_propagated(
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.side_effect = TranscriptionDailyLimitError("daily")
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq"}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    with pytest.raises(TranscriptionDailyLimitError, match="daily"):
        engine.transcribe_audio(audio_path, [], metadata, workspace)

    assert workspace.asr_fallback_used() is False


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
def test_primary_success_does_not_load_fallback(
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.return_value = [SubtitleEntry(0.0, 1.0, "primary")]
    fallback_factory = MagicMock(side_effect=AssertionError("fallback must stay lazy"))
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "fallback_backend": "remote"}}},
        primary_transcriber=primary,
        primary_backend="groq",
        fallback_backend="remote",
        fallback_transcriber_factory=fallback_factory,
    )

    result = engine.transcribe_audio(audio_path, [], metadata, workspace)

    assert result[0]["text"] == "primary"
    fallback_factory.assert_not_called()


@patch("yt2notion.segment._split_by_duration", side_effect=_segment_result)
@patch("yt2notion.audio.split_audio")
def test_full_audio_chunks_still_enforce_upload_budget(
    split_audio: MagicMock,
    _split_by_duration: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    audio_path.write_bytes(b"x" * 1000)
    oversized = tmp_path / "chunk_001.mp3"
    oversized.write_bytes(b"x" * 250)
    remaining = [tmp_path / f"chunk_{index:03d}.mp3" for index in range(2, 5)]
    for path in remaining:
        path.write_bytes(b"x" * 80)
    split_audio.return_value = [oversized, *remaining]
    primary = MagicMock(max_upload_bytes=200)
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 300}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    with pytest.raises(TranscriptionError, match="minimum chunk size"):
        engine.transcribe_audio(audio_path, [], metadata, workspace)

    primary.transcribe.assert_not_called()
    split_audio.assert_called_once()


@patch("yt2notion.audio.split_audio")
def test_oversized_segment_is_subdivided_before_upload(
    split_audio: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    oversized = tmp_path / "segment_001.mp3"
    oversized.write_bytes(b"x" * 180)
    children = [tmp_path / f"segment_001_child_{index}.mp3" for index in range(1, 3)]
    for path in children:
        path.write_bytes(b"x" * 90)
    split_audio.side_effect = [[oversized], children]
    primary = MagicMock(max_upload_bytes=100)
    primary.transcribe.side_effect = [
        [SubtitleEntry(0.0, 1.0, "child one")],
        [SubtitleEntry(0.0, 1.0, "child two")],
    ]
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "groq", "chunk_seconds": 300}}},
        primary_transcriber=primary,
        primary_backend="groq",
    )

    result = engine.transcribe_audio(
        audio_path,
        [{"title": "Long segment", "start_seconds": 0, "end_seconds": 120}],
        metadata,
        workspace,
    )

    assert result[0]["text"] == "child one child two"
    assert split_audio.call_count == 2
    assert [call.args[0] for call in primary.transcribe.call_args_list] == children


@patch("yt2notion.transcribe.engine._rebase_chunk_entries")
@patch("yt2notion.audio.split_audio")
def test_segmented_audio_without_upload_limit_keeps_direct_timestamps(
    split_audio: MagicMock,
    rebase_chunk_entries: MagicMock,
    tmp_path: Path,
    metadata: VideoMeta,
) -> None:
    workspace, audio_path = _audio_workspace(tmp_path, metadata)
    segment_file = tmp_path / "segment_001.mp3"
    segment_file.write_bytes(b"segment")
    split_audio.return_value = [segment_file]
    primary = MagicMock(max_upload_bytes=None)
    primary.transcribe.return_value = [
        SubtitleEntry(0.0, 0.4, "first"),
        SubtitleEntry(1.0, 3.0, "second"),
    ]
    rebase_chunk_entries.side_effect = AssertionError("segment entries must not be rebased")
    engine = TranscriptionEngine(
        {"extract": {"asr": {"backend": "remote"}}},
        primary_transcriber=primary,
        primary_backend="remote",
    )

    result = engine.transcribe_audio(
        audio_path,
        [{"title": "Part 1", "start_seconds": 100, "end_seconds": 130}],
        metadata,
        workspace,
    )

    assert result[0]["text"] == "first second"
    primary.transcribe.assert_called_once_with(segment_file, language=None)
    rebase_chunk_entries.assert_not_called()
