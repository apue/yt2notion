"""Tests for standalone media transcription workflow."""

from __future__ import annotations

from pathlib import Path

import pytest

from yt2notion.config import AppConfig, ConfigError
from yt2notion.media_transcribe import (
    render_media_transcript_markdown,
    resolve_media_transcribe_config_path,
    transcribe_media,
)
from yt2notion.models.base import VideoMeta


def test_resolve_config_prefers_user_config_path(monkeypatch, tmp_path: Path) -> None:
    user_config = tmp_path / "user-config.yaml"
    repo_config = tmp_path / "config.yaml"
    user_config.write_text("workspace: {}\n", encoding="utf-8")
    repo_config.write_text("workspace: {}\n", encoding="utf-8")

    monkeypatch.setattr("yt2notion.media_transcribe.DEFAULT_USER_CONFIG_PATH", user_config)
    monkeypatch.setattr("yt2notion.media_transcribe.DEFAULT_REPO_CONFIG_PATH", repo_config)

    assert resolve_media_transcribe_config_path(None) == user_config


def test_resolve_config_uses_explicit_path(tmp_path: Path) -> None:
    explicit = tmp_path / "config.yaml"
    explicit.write_text("workspace: {}\n", encoding="utf-8")

    assert resolve_media_transcribe_config_path(str(explicit)) == explicit


def test_resolve_config_errors_when_no_candidate(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr("yt2notion.media_transcribe.DEFAULT_USER_CONFIG_PATH", tmp_path / "user")
    monkeypatch.setattr("yt2notion.media_transcribe.DEFAULT_REPO_CONFIG_PATH", tmp_path / "repo")

    with pytest.raises(ConfigError, match="Config file not found"):
        resolve_media_transcribe_config_path(None)


def test_transcribe_media_writes_workspace_artifacts(monkeypatch, tmp_path: Path) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path / "workspace")}
    cfg.extract["cookies_from"] = None
    cfg.extract["asr"]["backend"] = "groq"
    cfg.extract["asr"]["fallback_backend"] = None
    cfg.output["max_segment_seconds"] = 900

    metadata = VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://example.com/video",
        duration_seconds=60,
        subtitles_available=False,
    )

    def fake_extract_video(url: str, output_dir: Path, **kwargs) -> Path:
        path = output_dir / "abc123.mp4"
        path.write_bytes(b"video")
        return path

    def fake_extract_audio_from_video(video_path: Path, output_path: Path) -> Path:
        output_path.write_bytes(b"audio")
        return output_path

    transcript_text = "hello"
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_metadata", lambda url: metadata)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_video", fake_extract_video)
    monkeypatch.setattr(
        "yt2notion.media_source.ytdlp.extract_audio_from_video",
        fake_extract_audio_from_video,
    )
    monkeypatch.setattr(
        "yt2notion.transcribe.engine.TranscriptionEngine.transcribe_audio",
        lambda self, *args, **kwargs: [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 10,
                "text": transcript_text,
                "source": "asr",
            }
        ],
    )

    result = transcribe_media("https://example.com/video", cfg)

    assert result.workspace.dir == tmp_path / "workspace" / "abc123"
    assert result.video_path == result.workspace.dir / "video.mp4"
    assert result.audio_path == result.workspace.dir / "audio.mp3"
    assert result.transcripts_path.exists()
    assert result.transcript_markdown_path.exists()
    assert "TestChannel" in result.transcript_markdown_path.read_text(encoding="utf-8")
    assert "hello" in result.transcript_markdown_path.read_text(encoding="utf-8")


def test_transcribe_media_no_video_clears_stale_video_and_markdown(
    monkeypatch,
    tmp_path: Path,
) -> None:
    cfg = AppConfig()
    cfg.workspace = {"base_dir": str(tmp_path / "workspace")}
    cfg.extract["cookies_from"] = None
    cfg.extract["asr"]["backend"] = "groq"
    cfg.extract["asr"]["fallback_backend"] = None

    workspace_dir = tmp_path / "workspace" / "abc123"
    workspace_dir.mkdir(parents=True)
    (workspace_dir / "video.mp4").write_bytes(b"old video")
    (workspace_dir / "transcript.md").write_text("old transcript", encoding="utf-8")

    metadata = VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://example.com/video",
        duration_seconds=60,
        subtitles_available=False,
    )

    def fake_extract_video(url: str, output_dir: Path, **kwargs) -> Path:
        path = output_dir / "abc123.mp4"
        path.write_bytes(b"new video")
        return path

    def fake_extract_audio_from_video(video_path: Path, output_path: Path) -> Path:
        output_path.write_bytes(b"audio")
        return output_path

    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_metadata", lambda url: metadata)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_video", fake_extract_video)
    monkeypatch.setattr(
        "yt2notion.media_source.ytdlp.extract_audio_from_video",
        fake_extract_audio_from_video,
    )
    monkeypatch.setattr(
        "yt2notion.transcribe.engine.TranscriptionEngine.transcribe_audio",
        lambda self, *args, **kwargs: [
            {
                "title": "Part 1",
                "start_seconds": 0,
                "end_seconds": 10,
                "text": "fresh transcript",
                "source": "asr",
            }
        ],
    )

    result = transcribe_media("https://example.com/video", cfg, keep_video=False)

    assert result.video_path is None
    assert not (workspace_dir / "video.mp4").exists()
    assert "fresh transcript" in (workspace_dir / "transcript.md").read_text(encoding="utf-8")
    assert "old transcript" not in (workspace_dir / "transcript.md").read_text(encoding="utf-8")


def test_render_media_transcript_markdown_includes_source() -> None:
    metadata = VideoMeta(
        video_id="abc123",
        title="Test Video",
        channel="TestChannel",
        url="https://example.com/video",
    )

    output = render_media_transcript_markdown(
        metadata,
        [
            {
                "title": "Intro",
                "start_seconds": 65,
                "end_seconds": 80,
                "text": "hello world",
                "source": "asr",
            }
        ],
        "groq",
    )

    assert "# Transcript: Test Video" in output
    assert "- Channel: TestChannel" in output
    assert "- URL: https://example.com/video" in output
    assert "- ASR backend: groq" in output
    assert "## [1:05] Intro" in output
    assert "hello world" in output
