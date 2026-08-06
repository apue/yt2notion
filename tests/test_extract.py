"""Tests for yt-dlp extraction (all mocked, no network)."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock, patch

import pytest

from yt2notion.extract import (
    ExtractionError,
    extract_metadata,
    extract_subtitles_with_source,
    extract_video,
    extract_webpage_transcript,
    write_transcript_srt,
)
from yt2notion.models.base import VideoMeta
from yt2notion.process import SubtitleEntry

SAMPLE_YTDLP_JSON = {
    "id": "abc123",
    "title": "Test Video Title",
    "channel": "TestChannel",
    "uploader": "TestUploader",
    "upload_date": "20260319",
    "webpage_url": "https://www.youtube.com/watch?v=abc123",
    "duration": 600,
    "subtitles": {"en": [{"ext": "vtt"}]},
    "automatic_captions": {"en": [{"ext": "vtt"}], "zh-Hans-en": [{"ext": "vtt"}]},
}


@patch("yt2notion.extract.subprocess.run")
def test_extract_metadata_parsing(mock_run):
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(SAMPLE_YTDLP_JSON), stderr=""
    )
    meta = extract_metadata("https://www.youtube.com/watch?v=abc123")
    assert meta.video_id == "abc123"
    assert meta.title == "Test Video Title"
    assert meta.channel == "TestChannel"
    assert meta.duration_seconds == 600
    assert meta.upload_date == "20260319"
    assert "--no-playlist" in mock_run.call_args.args[0]
    assert meta.manual_subtitle_languages == ["en"]
    assert meta.automatic_caption_languages == ["en", "zh-Hans-en"]


@patch("yt2notion.extract.subprocess.run")
def test_subtitle_selection_downloads_one_available_manual_track(mock_run, tmp_path):
    metadata = VideoMeta(
        video_id="abc123",
        title="Test",
        channel="Channel",
        manual_subtitle_languages=["en"],
        automatic_caption_languages=["en"],
    )

    def side_effect(cmd, **kwargs):
        (tmp_path / "abc123.en.srt").write_text(
            "1\n00:00:01,000 --> 00:00:02,000\nHello\n",
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect
    path, source = extract_subtitles_with_source(
        "https://www.youtube.com/watch?v=abc123",
        {"extract": {"subtitle_priority": ["zh-Hans", "en"]}},
        tmp_path,
        metadata=metadata,
    )

    assert path.name == "abc123.en.srt"
    assert source == "manual_subtitle"
    assert mock_run.call_count == 1
    assert "en" in mock_run.call_args.args[0]


@patch("yt2notion.extract.subprocess.run")
def test_extract_metadata_uses_uploader_fallback(mock_run):
    data = dict(SAMPLE_YTDLP_JSON)
    del data["channel"]
    mock_run.return_value = subprocess.CompletedProcess(
        args=[], returncode=0, stdout=json.dumps(data), stderr=""
    )
    meta = extract_metadata("https://www.youtube.com/watch?v=abc123")
    assert meta.channel == "TestUploader"


@patch("yt2notion.extract.subprocess.run")
def test_subtitle_fallback_to_auto(mock_run, tmp_path):
    """When no manual subs exist, fall back to auto-generated."""

    def side_effect(cmd, **kwargs):
        if "--write-auto-sub" in cmd:
            srt_file = tmp_path / "abc123.en.srt"
            srt_file.write_text("1\n00:00:01,000 --> 00:00:02,000\nAuto sub\n")
            return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")
        # Manual sub downloads produce no files
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect
    config = {
        "extract": {
            "subtitle_priority": ["zh-Hans"],
            "auto_subtitle_fallback": True,
            "auto_subtitle_lang": "en",
            "cookies_from": None,
        }
    }
    path, source = extract_subtitles_with_source(
        "https://www.youtube.com/watch?v=abc123",
        config,
        tmp_path,
        metadata=VideoMeta(
            video_id="abc123",
            title="Test",
            channel="Channel",
            automatic_caption_languages=["en"],
        ),
    )
    assert path.exists()
    assert source == "auto_caption"


@patch("yt2notion.extract.subprocess.run")
def test_extraction_error_on_failure(mock_run):
    mock_run.side_effect = subprocess.CalledProcessError(1, "yt-dlp", stderr="some error")
    with pytest.raises(ExtractionError, match="yt-dlp failed"):
        extract_metadata("https://www.youtube.com/watch?v=bad")


@patch("yt2notion.extract.subprocess.run")
def test_extraction_error_not_installed(mock_run):
    mock_run.side_effect = FileNotFoundError()
    with pytest.raises(ExtractionError, match="yt-dlp not found"):
        extract_metadata("https://www.youtube.com/watch?v=abc123")


@patch("yt2notion.extract.subprocess.run")
def test_cookies_flag(mock_run, tmp_path):
    """Verify cookies_from config adds the correct flag."""
    calls = []

    def side_effect(cmd, **kwargs):
        calls.append(cmd)
        raise subprocess.CalledProcessError(1, "yt-dlp", stderr="no subs")

    mock_run.side_effect = side_effect
    config = {
        "extract": {
            "subtitle_priority": ["en"],
            "auto_subtitle_fallback": False,
            "cookies_from": "chrome",
        }
    }
    with pytest.raises(ExtractionError):
        extract_subtitles_with_source(
            "https://www.youtube.com/watch?v=abc123",
            config,
            tmp_path,
            metadata=VideoMeta(
                video_id="abc123",
                title="Test",
                channel="Channel",
                manual_subtitle_languages=["en"],
            ),
        )
    assert len(calls) == 2
    assert "--cookies-from-browser" not in calls[0]
    assert calls[1][calls[1].index("--cookies-from-browser") + 1] == "chrome"


@patch("yt2notion.extract.subprocess.run")
def test_extract_video_downloads_playable_media(mock_run, tmp_path):
    def side_effect(cmd, **kwargs):
        video = tmp_path / "abc123.mp4"
        video.write_bytes(b"video")
        return subprocess.CompletedProcess(args=cmd, returncode=0, stdout="", stderr="")

    mock_run.side_effect = side_effect

    path = extract_video(
        "https://www.youtube.com/watch?v=abc123",
        tmp_path,
        video_id="abc123",
        cookies_from="chrome",
    )

    assert path == tmp_path / "abc123.mp4"
    cmd = mock_run.call_args.args[0]
    assert "--merge-output-format" in cmd
    assert "--cookies-from-browser" in cmd


@patch("yt2notion.extract.httpx.get")
def test_extract_webpage_transcript_follows_episode_webpage_link(mock_get):
    apple_page = """
    <html><body>
      <a href="https://www.acquired.fm/episodes/google-the-ai-company">
        <span>Episode Webpage</span>
      </a>
    </body></html>
    """
    acquired_page = """
    <html><body>
      <div class="transcript-container">
        <div id="transcript" class="rich-text-block-7 w-richtext">
          <p><strong>Transcript:</strong></p>
        </div>
        <div class="rich-text-block-6 w-richtext">
          <p>Ben: Welcome.</p>
          <p>David: Let&apos;s go.</p>
        </div>
      </div>
    </body></html>
    """
    apple_response = Mock()
    apple_response.raise_for_status.return_value = None
    apple_response.text = apple_page
    acquired_response = Mock()
    acquired_response.raise_for_status.return_value = None
    acquired_response.text = acquired_page
    mock_get.side_effect = [apple_response, acquired_response]

    entries = extract_webpage_transcript(
        "https://podcasts.apple.com/us/podcast/example/id1?i=2",
        VideoMeta(video_id="2", title="Example", channel="Example", duration_seconds=120),
    )

    assert [entry.text for entry in entries] == ["Ben: Welcome.", "David: Let's go."]
    assert entries[0].start_seconds == pytest.approx(0.0)
    assert entries[0].end_seconds == pytest.approx(60.0)
    assert entries[1].start_seconds == pytest.approx(60.0)
    assert entries[1].end_seconds == pytest.approx(120.0)


def test_write_transcript_srt(tmp_path):
    output_path = tmp_path / "transcript.srt"
    path = write_transcript_srt(
        [
            SubtitleEntry(start_seconds=0.0, end_seconds=5.25, text="Hello world"),
        ],
        output_path,
    )
    assert path == output_path
    assert output_path.read_text(encoding="utf-8") == (
        "1\n00:00:00,000 --> 00:00:05,250\nHello world\n"
    )
