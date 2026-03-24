"""Tests for the segmentation module."""

from __future__ import annotations

from yt2notion.models.base import Chapter, VideoMeta
from yt2notion.process import SubtitleEntry
from yt2notion.segment import (
    _find_sentence_boundary,
    _parse_description_timestamps,
    segment,
)


def _make_entries(intervals: list[tuple[float, float, str]]) -> list[SubtitleEntry]:
    """Helper to create subtitle entries."""
    return [SubtitleEntry(start_seconds=s, end_seconds=e, text=t) for s, e, t in intervals]


def _make_meta(**kwargs) -> VideoMeta:
    return VideoMeta(video_id="test", title="Test", channel="Test", **kwargs)


class TestSegmentByChapters:
    def test_short_chapters_no_subdivision(self):
        chapters = [
            Chapter(title="Intro", start_seconds=0, end_seconds=300),
            Chapter(title="Main", start_seconds=300, end_seconds=600),
        ]
        entries = _make_entries(
            [
                (0, 5, "Hello"),
                (100, 105, "World"),
                (300, 305, "Main topic"),
                (500, 505, "Details"),
            ]
        )
        meta = _make_meta(chapters=chapters)
        segments = segment(entries, meta, max_segment_seconds=900)

        assert len(segments) == 2
        assert segments[0].title == "Intro"
        assert segments[1].title == "Main"
        assert "Hello" in segments[0].text
        assert "Main topic" in segments[1].text
        assert segments[0].parent_title is None

    def test_long_chapter_gets_subdivided(self):
        chapters = [
            Chapter(title="Very Long Section", start_seconds=0, end_seconds=2000),
        ]
        # Create entries spanning 2000 seconds
        entries = _make_entries(
            [(i * 100, i * 100 + 5, f"Text at {i * 100}s. End of thought.") for i in range(20)]
        )
        meta = _make_meta(chapters=chapters)
        segments = segment(entries, meta, max_segment_seconds=500)

        assert len(segments) > 1
        assert all(s.parent_title == "Very Long Section" for s in segments if s.parent_title)

    def test_empty_entries(self):
        meta = _make_meta(chapters=[Chapter(title="A", start_seconds=0, end_seconds=100)])
        assert segment([], meta) == []


class TestDescriptionTimestamps:
    def test_parse_hms_format(self):
        desc = """OUTLINE:
00:01:19 The normal one
00:35:40 世界总不让我做Vision
01:37:50 杨立昆和李飞飞往事
"""
        result = _parse_description_timestamps(desc, 7200)
        assert len(result) == 3
        assert result[0].title == "The normal one"
        assert result[0].start_seconds == 79
        assert result[1].start_seconds == 2140
        assert result[2].end_seconds == 7200  # last chapter goes to total duration

    def test_parse_ms_format(self):
        desc = """
0:00 Introduction
5:30 Main topic
12:00 Conclusion
"""
        result = _parse_description_timestamps(desc, 900)
        assert len(result) == 3
        assert result[0].start_seconds == 0
        assert result[1].start_seconds == 330

    def test_too_few_timestamps(self):
        desc = "Just one 0:00 timestamp here"
        result = _parse_description_timestamps(desc, 600)
        assert result == []

    def test_description_fallback_in_segment(self):
        """When no chapters but description has timestamps."""
        entries = _make_entries(
            [
                (0, 5, "Hello"),
                (330, 335, "Main"),
                (720, 725, "End"),
            ]
        )
        meta = _make_meta(
            description="0:00 Intro\n5:30 Main\n12:00 End",
            duration_seconds=900,
        )
        segments = segment(entries, meta, max_segment_seconds=900)
        assert len(segments) >= 2


class TestDurationSplit:
    def test_pure_duration_split(self):
        entries = _make_entries([(i * 60, i * 60 + 5, f"Text {i}") for i in range(30)])
        meta = _make_meta(duration_seconds=1800)
        segments = segment(entries, meta, max_segment_seconds=600)

        assert len(segments) >= 3
        assert all(s.title.startswith("Part ") for s in segments)


class TestSentenceBoundary:
    def test_chinese_boundary(self):
        text = "这是第一句话。这是第二句话。这是第三句话。这是第四句话。"
        idx = _find_sentence_boundary(text)
        assert idx is not None
        assert text[idx - 1] in "。"

    def test_english_boundary(self):
        text = "First sentence. Second sentence. Third sentence. Fourth sentence."
        idx = _find_sentence_boundary(text)
        assert idx is not None
        assert text[idx - 2] == "."

    def test_no_boundary(self):
        text = "no punctuation here just words"
        idx = _find_sentence_boundary(text)
        assert idx is None
