"""Tests for workspace module."""

from __future__ import annotations

from yt2notion.models.base import ChineseContent, Entity, EntityResult, VideoMeta
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
    assert STEPS == ("download", "segment", "transcribe", "review", "extract", "summarize")


def test_entities_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    result = EntityResult(
        domain="food/dining",
        is_entity_centric=True,
        entity_types=["restaurant", "dish"],
        entities=[
            Entity(name="Gaggan", type="restaurant", attributes={"city": "Bangkok"}, linkable=True),
            Entity(name="Curry Crab", type="dish", attributes={}, linkable=False),
        ],
        relations=[{"from": "Gaggan", "relation": "serves", "to": "Curry Crab"}],
    )
    ws.save_entities(result)
    loaded = ws.load_entities()
    assert loaded is not None
    assert loaded.domain == "food/dining"
    assert loaded.is_entity_centric is True
    assert len(loaded.entities) == 2
    assert loaded.entities[0].name == "Gaggan"
    assert loaded.entities[0].attributes == {"city": "Bangkok"}
    assert loaded.entities[1].linkable is False
    assert len(loaded.relations) == 1


def test_load_entities_missing(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.load_entities() is None


def test_step_done_extract(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert not ws.step_done("extract")
    result = EntityResult(
        domain="",
        is_entity_centric=False,
        entity_types=[],
        entities=[],
        relations=[],
    )
    ws.save_entities(result)
    assert ws.step_done("extract")


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


def test_asr_fallback_marker_roundtrip(tmp_path):
    ws = Workspace(tmp_path, "test123")
    assert ws.asr_fallback_used() is False

    ws.mark_asr_fallback_used()

    assert ws.asr_fallback_used() is True
