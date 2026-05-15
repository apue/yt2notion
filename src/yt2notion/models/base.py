"""Model backend Protocol definitions."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

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
    description: str = ""
    language: str = ""
    subtitles_available: bool = False
    series: str = ""  # podcast series name (fallback for channel)


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
class ChineseContent:
    """Legacy single-note content retained for storage backends not on the runtime path."""

    overview: str
    key_points: list[dict]
    tags: list[str]
    raw_markdown: str
    mindmap: str = ""
    fun_facts: dict[str, list[str]] = field(default_factory=dict)


@dataclass
class NoteMetadata:
    """Structured metadata for the source/A/B bundle."""

    source_title: str
    stable_tags: list[str]
    guide_tags: list[str]
    longform_tags: list[str]
    source_summary: str
    source_topics: list[str]


NOTE_VARIANT_SOURCE = "source"
NOTE_VARIANT_GUIDE = "a_guide"
NOTE_VARIANT_LONGFORM = "b_longform"
NoteVariant = Literal["source", "a_guide", "b_longform"]


@dataclass
class NoteDocument:
    """A single note within a source/A/B bundle."""

    title: str
    markdown: str
    tags: list[str]
    variant: NoteVariant


@dataclass
class NoteBundle:
    """Structured source plus A/B note bundle output."""

    source: NoteDocument
    guide: NoteDocument
    longform: NoteDocument
    stable_tags: list[str]
    source_topics: list[str]


FUN_FACTS_CATEGORIES: dict[str, str] = {
    "hot_takes": "🔥 犀利观点",
    "nerd_stats": "🤓 极客冷知识",
    "media_mentions": "📚 作品提及",
}


@dataclass
class Entity:
    """A named entity extracted from content."""

    name: str
    type: str
    attributes: dict[str, str] = field(default_factory=dict)
    linkable: bool = True


@dataclass
class EntityResult:
    """Complete entity extraction output."""

    domain: str
    is_entity_centric: bool
    entity_types: list[str]
    entities: list[Entity]
    relations: list[dict]  # [{from, relation, to}]


class Summarizer(Protocol):
    """Protocol for LLM summarization backends."""

    def compose_guide_note(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_guide",
    ) -> NoteDocument:
        """Compose the guide note as strict JSON output."""
        ...

    def compose_longform_note(
        self,
        transcript: str,
        guide_note: NoteDocument,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_longform",
    ) -> NoteDocument:
        """Compose the longform note using the guide note as a scaffold."""
        ...

    def compose_note_metadata(
        self,
        guide_note: NoteDocument,
        longform_note: NoteDocument,
        metadata: VideoMeta,
        *,
        prompt_name: str = "compose_note_metadata",
    ) -> NoteMetadata:
        """Compose note-bundle metadata from guide and longform notes."""
        ...
