"""Tests for workspace module."""

from __future__ import annotations

import json

import pytest

from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta
from yt2notion.workspace import STEPS, Workspace


def test_workspace_creation(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.dir == tmp_path / "test123"
    assert ws.dir.exists()


def test_metadata_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    meta = VideoMeta(
        video_id="test123",
        title="Test",
        channel="Chan",
        manual_subtitle_languages=["en"],
        series="MySeries",
    )
    ws.save_metadata(meta)
    loaded = ws.load_metadata()
    assert loaded.video_id == "test123"
    assert loaded.title == "Test"
    assert loaded.subtitles_available is True
    assert loaded.series == "MySeries"


def test_segments_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    segs = [{"title": "Intro", "start_seconds": 0, "end_seconds": 300}]
    ws.save_segments(segs)
    loaded = ws.load_segments()
    assert loaded == segs


def test_step_done(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert not ws.step_done("download")
    ws.save_metadata(VideoMeta(video_id="x", title="T", channel="C"))
    assert ws.step_done("download")


def test_audio_path(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.audio_path is None

    audio = tmp_path / "source.mp3"
    audio.write_bytes(b"fake audio")
    saved = ws.save_audio(audio)
    assert ws.audio_path == saved
    assert saved.name == "audio.mp3"


def test_video_path(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.video_path is None

    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake video")
    saved = ws.save_video(video)
    assert ws.video_path == saved
    assert saved.name == "video.mp4"


def test_discard_video_artifacts(tmp_path):
    ws = Workspace(tmp_path, "test123")
    (ws.dir / "video.mp4").write_bytes(b"old")
    (ws.dir / "video.webm").write_bytes(b"old")

    ws.discard_video_artifacts()

    assert ws.video_path is None
    assert not (ws.dir / "video.mp4").exists()
    assert not (ws.dir / "video.webm").exists()


def test_subtitle_path(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.subtitle_path is None

    srt = tmp_path / "source.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    saved = ws.save_subtitles(srt)
    assert ws.subtitle_path == saved
    assert saved.name == "subtitles.srt"


def test_subtitle_source_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.load_subtitle_source() is None

    ws.save_subtitle_source("auto_caption")

    assert ws.load_subtitle_source() == "auto_caption"


def test_failure_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    ws.save_failure("https://example.com", "summarize", "boom", retries_exhausted=True)

    loaded = ws.load_failure()
    assert loaded is not None
    assert loaded["url"] == "https://example.com"
    assert loaded["step"] == "summarize"
    assert loaded["error"] == "boom"
    assert loaded["retries_exhausted"] is True
    assert "timestamp" in loaded

    ws.clear_failure()
    assert ws.load_failure() is None
    assert not (tmp_path / "test123" / "failed.json").exists()


def test_steps_constant():
    assert STEPS == ("download", "segment", "transcribe", "review", "summarize")


def test_discard_transcribe_artifacts_removes_transcripts_and_chunk_dirs(tmp_path):
    ws = Workspace(tmp_path, "test123")
    ws.save_transcripts(
        [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 10,
                "text": "before",
                "source": "asr",
            }
        ]
    )
    (ws.dir / "segments").mkdir(parents=True, exist_ok=True)
    (ws.dir / "segments" / "segment_001.mp3").write_bytes(b"fake")
    (ws.dir / "full_audio_chunks").mkdir(parents=True, exist_ok=True)
    (ws.dir / "full_audio_chunks" / "chunk_001.mp3").write_bytes(b"fake")

    ws.discard_transcribe_artifacts()

    assert ws.load_transcripts() is None
    assert not (ws.dir / "segments").exists()
    assert not (ws.dir / "full_audio_chunks").exists()


def test_transcribe_plan_state_and_chunk_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    plan = [
        {
            "chunk_id": "chunk-001",
            "title": "Part 1",
            "start_seconds": 0,
            "end_seconds": 120,
            "audio_relpath": "full_audio_chunks/chunk_001.mp3",
            "preferred_backend": "groq",
        }
    ]
    state = {
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
            }
        ],
    }
    chunk_entries = [
        {
            "start_seconds": 0,
            "end_seconds": 30,
            "text": "chunk one",
            "source": "groq",
        },
        {
            "start_seconds": 30,
            "end_seconds": 60,
            "text": "chunk two",
            "source": "groq",
        },
    ]

    ws.save_transcribe_plan(plan)
    ws.save_transcribe_state(state)
    ws.save_transcribe_chunk_result("chunk-001", chunk_entries)

    assert ws.load_transcribe_plan() == plan
    assert ws.load_transcribe_state() == state
    assert ws.load_transcribe_chunk_result("chunk-001") == chunk_entries
    assert (ws.dir / "transcribe_plan.json").exists()
    assert (ws.dir / "transcribe_state.json").exists()
    assert (ws.dir / "transcribe_chunks" / "chunk-001.json").exists()


def test_asr_fallback_marker_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.asr_fallback_used() is False

    ws.mark_asr_fallback_used()

    assert ws.asr_fallback_used() is True


def test_note_bundle_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    bundle = NoteBundle(
        source=NoteDocument(
            title="source",
            markdown="# source",
            tags=["法拉利"],
            variant="source",
        ),
        guide=NoteDocument(
            title="guide",
            markdown="# guide",
            tags=["导读版"],
            variant="a_guide",
        ),
        longform=NoteDocument(
            title="long",
            markdown="# long",
            tags=["扩展版"],
            variant="b_longform",
        ),
        stable_tags=["法拉利", "赛车"],
        source_topics=["稀缺机制", "电动化挑战"],
    )

    ws.save_note_bundle(bundle)
    loaded = ws.load_note_bundle()

    assert loaded is not None
    assert loaded == bundle
    assert ws.step_done("summarize") is True


def test_load_note_bundle_rejects_variant_mismatch(tmp_path):
    ws = Workspace(tmp_path, "test123")
    ws.dir.mkdir(parents=True, exist_ok=True)
    (ws.dir / "note_bundle.json").write_text(
        json.dumps(
            {
                "source": {
                    "title": "source",
                    "markdown": "# source",
                    "tags": ["法拉利"],
                    "variant": "source",
                },
                "guide": {
                    "title": "guide",
                    "markdown": "# guide",
                    "tags": ["导读版"],
                    "variant": "wrong",
                },
                "longform": {
                    "title": "long",
                    "markdown": "# long",
                    "tags": ["扩展版"],
                    "variant": "b_longform",
                },
                "stable_tags": ["法拉利", "赛车"],
                "source_topics": ["稀缺机制", "电动化挑战"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    with pytest.raises(ValueError, match="variant"):
        ws.load_note_bundle()


def test_save_note_bundle_rejects_variant_mismatch_before_write(tmp_path):
    ws = Workspace(tmp_path, "test123")
    bundle = NoteBundle(
        source=NoteDocument(
            title="source",
            markdown="# source",
            tags=["法拉利"],
            variant="source",
        ),
        guide=NoteDocument(
            title="guide",
            markdown="# guide",
            tags=["导读版"],
            variant="wrong",
        ),
        longform=NoteDocument(
            title="long",
            markdown="# long",
            tags=["扩展版"],
            variant="b_longform",
        ),
        stable_tags=["法拉利", "赛车"],
        source_topics=["稀缺机制", "电动化挑战"],
    )

    with pytest.raises(ValueError, match="variant"):
        ws.save_note_bundle(bundle)

    assert not (ws.dir / "note_bundle.json").exists()


def test_load_note_bundle_requires_stable_tags_and_source_topics(tmp_path):
    ws = Workspace(tmp_path, "test123")
    ws.dir.mkdir(parents=True, exist_ok=True)
    (ws.dir / "note_bundle.json").write_text(
        json.dumps(
            {
                "source": {
                    "title": "source",
                    "markdown": "# source",
                    "tags": ["法拉利"],
                    "variant": "source",
                },
                "guide": {
                    "title": "guide",
                    "markdown": "# guide",
                    "tags": ["导读版"],
                    "variant": "a_guide",
                },
                "longform": {
                    "title": "long",
                    "markdown": "# long",
                    "tags": ["扩展版"],
                    "variant": "b_longform",
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )

    with pytest.raises(ValueError, match="stable_tags"):
        ws.load_note_bundle()


def test_discard_transcribe_artifacts_removes_checkpoint_files(tmp_path):
    ws = Workspace(tmp_path, "test123")
    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 120,
                "audio_relpath": "full_audio_chunks/chunk_001.mp3",
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
            "chunks": [],
        }
    )
    ws.save_transcribe_chunk_result(
        "chunk-001",
        [{"start_seconds": 0, "end_seconds": 30, "text": "chunk one", "source": "groq"}],
    )
    (ws.dir / "segments").mkdir(parents=True, exist_ok=True)
    (ws.dir / "segments" / "segment_001.mp3").write_bytes(b"fake")

    ws.discard_transcribe_artifacts()

    assert ws.load_transcribe_plan() is None
    assert ws.load_transcribe_state() is None
    assert ws.load_transcribe_chunk_result("chunk-001") is None
    assert not (ws.dir / "transcribe_chunks").exists()
    assert not (ws.dir / "transcribe_plan.json").exists()
    assert not (ws.dir / "transcribe_state.json").exists()
    assert not (ws.dir / "segments").exists()


def test_discard_transcribe_artifacts_with_audio_path_removes_audio_relative_dirs(tmp_path):
    ws = Workspace(tmp_path, "test123")
    audio = tmp_path / "episode.mp3"
    audio.write_bytes(b"fake audio")
    saved_audio = ws.save_audio(audio)

    ws.save_transcribe_plan(
        [
            {
                "chunk_id": "chunk-001",
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 120,
                "audio_relpath": "full_audio_chunks/chunk_001.mp3",
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
            "chunks": [],
        }
    )
    ws.save_transcribe_chunk_result(
        "chunk-001",
        [{"start_seconds": 0, "end_seconds": 30, "text": "chunk one", "source": "groq"}],
    )
    (saved_audio.parent / "segments").mkdir(parents=True, exist_ok=True)
    (saved_audio.parent / "segments" / "segment_001.mp3").write_bytes(b"fake")
    (saved_audio.parent / "full_audio_chunks").mkdir(parents=True, exist_ok=True)
    (saved_audio.parent / "full_audio_chunks" / "chunk_001.mp3").write_bytes(b"fake")

    ws.discard_transcribe_artifacts(audio_path=saved_audio)

    assert ws.load_transcribe_plan() is None
    assert ws.load_transcribe_state() is None
    assert ws.load_transcribe_chunk_result("chunk-001") is None
    assert not (saved_audio.parent / "segments").exists()
    assert not (saved_audio.parent / "full_audio_chunks").exists()
