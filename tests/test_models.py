"""Tests for core data models."""

from yt2notion.models.base import VideoMeta


def test_video_meta() -> None:
    metadata = VideoMeta(
        title="Test Video",
        channel="TestChannel",
        url="https://youtube.com/watch?v=abc",
        video_id="abc",
    )

    assert metadata.title == "Test Video"
    assert metadata.video_id == "abc"
