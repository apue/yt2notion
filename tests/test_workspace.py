"""Tests for workspace module."""

from __future__ import annotations

from yt2notion.models.base import ChineseContent, VideoMeta
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
        subtitles_available=True,
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


def test_subtitle_path(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.subtitle_path is None

    srt = tmp_path / "source.srt"
    srt.write_text("1\n00:00:01,000 --> 00:00:02,000\nHi\n")
    saved = ws.save_subtitles(srt)
    assert ws.subtitle_path == saved
    assert saved.name == "subtitles.srt"


def test_summary_save(tmp_path):
    ws = Workspace(tmp_path, "test123")
    content = ChineseContent(overview="概要", key_points=[], tags=["test"], raw_markdown="# Test")
    ws.save_summary(content)
    assert ws.step_done("summarize")


def test_steps_constant():
    assert STEPS == ("download", "segment", "transcribe", "review", "summarize")
