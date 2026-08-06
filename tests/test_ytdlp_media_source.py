"""Contract tests for subtitle-first yt-dlp media acquisition."""

from __future__ import annotations

from pathlib import Path

from yt2notion.media_source.base import MediaAcquireRequest
from yt2notion.media_source.ytdlp import YtDlpMediaSource
from yt2notion.models.base import VideoMeta


def test_captioned_video_skips_media_download(monkeypatch, tmp_path: Path) -> None:
    metadata = VideoMeta(
        video_id="captioned",
        title="Captioned",
        channel="Channel",
        duration_seconds=60,
        manual_subtitle_languages=["en"],
    )

    def fake_subtitles(url, config, output_dir, *, metadata):
        path = output_dir / "captioned.en.srt"
        path.write_text("1\n00:00:00,000 --> 00:00:01,000\nHello\n", encoding="utf-8")
        return path, "manual_subtitle"

    def forbidden(*args, **kwargs):
        raise AssertionError("captioned acquisition must not download media")

    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_metadata", lambda url: metadata)
    monkeypatch.setattr(
        "yt2notion.media_source.ytdlp.extract_subtitles_with_source",
        fake_subtitles,
    )
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_audio", forbidden)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_video", forbidden)

    result = YtDlpMediaSource({"extract": {}}).acquire(
        MediaAcquireRequest(
            url="https://example.com/captioned",
            workspace_base_dir=tmp_path,
            keep_video=False,
        )
    )

    assert result.subtitle_path == result.workspace.dir / "subtitles.srt"
    assert result.subtitle_source == "manual_subtitle"
    assert result.audio_path is None
    assert result.video_path is None


def test_no_video_fallback_downloads_audio_directly(monkeypatch, tmp_path: Path) -> None:
    metadata = VideoMeta(
        video_id="audio-only",
        title="Audio only",
        channel="Channel",
        duration_seconds=60,
    )

    def fake_audio(url, output_dir, **kwargs):
        path = output_dir / "audio-only.mp3"
        path.write_bytes(b"audio")
        return path

    def forbidden(*args, **kwargs):
        raise AssertionError("--no-video fallback must not download video")

    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_metadata", lambda url: metadata)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_webpage_transcript", lambda *a: [])
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_audio", fake_audio)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_video", forbidden)

    result = YtDlpMediaSource({"extract": {}}).acquire(
        MediaAcquireRequest(
            url="https://example.com/audio-only",
            workspace_base_dir=tmp_path,
            keep_video=False,
        )
    )

    assert result.audio_path == result.workspace.dir / "audio.mp3"
    assert result.video_path is None
    assert result.subtitle_path is None


def test_fresh_acquisition_discards_stale_source_artifacts(monkeypatch, tmp_path: Path) -> None:
    workspace = tmp_path / "stale"
    workspace.mkdir()
    (workspace / "subtitles.vtt").write_text("old subtitle", encoding="utf-8")
    (workspace / "subtitle_source.json").write_text(
        '{"source":"manual_subtitle"}', encoding="utf-8"
    )
    (workspace / "audio.mp3").write_bytes(b"old audio")
    (workspace / "video.mp4").write_bytes(b"old video")
    metadata = VideoMeta(
        video_id="stale",
        title="Fresh",
        channel="Channel",
        duration_seconds=60,
    )

    def fake_audio(url, output_dir, **kwargs):
        path = output_dir / "stale.mp3"
        path.write_bytes(b"fresh audio")
        return path

    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_metadata", lambda url: metadata)
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_webpage_transcript", lambda *a: [])
    monkeypatch.setattr("yt2notion.media_source.ytdlp.extract_audio", fake_audio)

    result = YtDlpMediaSource({"extract": {}}).acquire(
        MediaAcquireRequest(
            url="https://example.com/stale",
            workspace_base_dir=tmp_path,
            keep_video=False,
        )
    )

    assert result.audio_path.read_bytes() == b"fresh audio"
    assert result.subtitle_path is None
    assert not (workspace / "subtitles.vtt").exists()
    assert not (workspace / "video.mp4").exists()
