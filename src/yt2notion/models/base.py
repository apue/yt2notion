"""Model backend Protocol definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol


@dataclass
class VideoMeta:
    """Metadata extracted from YouTube."""

    video_id: str
    title: str
    channel: str
    upload_date: str  # YYYYMMDD
    url: str
    duration_seconds: int = 0


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

    def summarize(self, transcript: str, metadata: VideoMeta) -> Summary:
        """Produce a structured summary with timestamps."""
        ...

    def to_chinese(self, summary: Summary, metadata: VideoMeta) -> ChineseContent:
        """Rewrite summary in natural Chinese."""
        ...
