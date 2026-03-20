"""Model backend Protocol definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from yt2notion.process import seconds_to_display


@dataclass
class Chapter:
    """A chapter defined by the video author."""

    title: str
    start_seconds: int
    end_seconds: int

    @property
    def timestamp_display(self) -> str:
        return seconds_to_display(self.start_seconds)


@dataclass
class VideoMeta:
    """Metadata extracted from YouTube."""

    video_id: str
    title: str
    channel: str
    upload_date: str = ""  # YYYYMMDD
    url: str = ""
    duration_seconds: int = 0
    chapters: list[Chapter] = field(default_factory=list)


@dataclass
class TimestampedSection:
    """A section with timestamp, used throughout the pipeline."""

    title: str
    timestamp_seconds: int
    content: str

    @property
    def timestamp_display(self) -> str:
        return seconds_to_display(self.timestamp_seconds)

    def youtube_link(self, video_id: str) -> str:
        """Generate a YouTube deep link to this timestamp."""
        return f"https://youtu.be/{video_id}?t={self.timestamp_seconds}"


@dataclass
class Section:
    """A key section identified in the video."""

    title: str
    timestamp: str  # MM:SS
    timestamp_seconds: int
    summary: str


@dataclass
class Summary:
    """Structured summary output from the summarize step."""

    sections: list[Section]
    overall_summary: str
    suggested_tags: list[str] = field(default_factory=list)

    def to_text(self) -> str:
        """Serialize for passing to the next LLM stage."""
        import json

        return json.dumps(
            {
                "sections": [
                    {
                        "title": s.title,
                        "timestamp": s.timestamp,
                        "timestamp_seconds": s.timestamp_seconds,
                        "summary": s.summary,
                    }
                    for s in self.sections
                ],
                "overall_summary": self.overall_summary,
                "suggested_tags": self.suggested_tags,
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class ChineseContent:
    """Final Chinese content ready for publishing."""

    overview: str
    key_points: list[dict]  # [{timestamp, title, summary}]
    tags: list[str]
    raw_markdown: str  # 完整的 markdown 输出


class Summarizer(Protocol):
    """Protocol for LLM summarization backends."""

    def summarize(
        self, transcript: str, metadata: VideoMeta, *, prompt_name: str = "summarize"
    ) -> Summary:
        """Produce a structured summary with timestamps."""
        ...

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        ...
