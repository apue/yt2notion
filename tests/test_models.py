"""Tests for data models in models/base.py."""

from yt2notion.models.base import TimestampedSection, VideoMeta


def test_timestamp_display():
    section = TimestampedSection(title="Test", timestamp_seconds=124, content="...")
    assert section.timestamp_display == "2:04"


def test_timestamp_display_zero():
    section = TimestampedSection(title="Intro", timestamp_seconds=1, content="...")
    assert section.timestamp_display == "0:01"


def test_youtube_link():
    section = TimestampedSection(title="Test", timestamp_seconds=243, content="...")
    link = section.youtube_link("abc123")
    assert link == "https://youtu.be/abc123?t=243"


def test_video_meta():
    meta = VideoMeta(
        title="Test Video",
        channel="TestChannel",
        url="https://youtube.com/watch?v=abc",
        video_id="abc",
    )
    assert meta.title == "Test Video"
    assert meta.video_id == "abc"
