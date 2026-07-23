"""Core metadata and note composition contracts."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from yt2notion.process import seconds_to_display


@dataclass
class Chapter:
    """A chapter defined by the media author."""

    title: str
    start_seconds: int
    end_seconds: int

    @property
    def timestamp_display(self) -> str:
        return seconds_to_display(self.start_seconds)


@dataclass
class VideoMeta:
    """Metadata extracted from a media source."""

    video_id: str
    title: str
    channel: str
    upload_date: str = ""
    url: str = ""
    duration_seconds: int = 0
    chapters: list[Chapter] = field(default_factory=list)
    description: str = ""
    language: str = ""
    subtitles_available: bool = False
    series: str = ""


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


class Summarizer(Protocol):
    """Compose the two generated notes and shared bundle metadata."""

    def compose_guide_note(
        self,
        transcript: str,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_guide",
    ) -> NoteDocument: ...

    def compose_longform_note(
        self,
        transcript: str,
        guide_note: NoteDocument,
        metadata: VideoMeta,
        *,
        target_chars: int,
        prompt_name: str = "compose_longform",
    ) -> NoteDocument: ...

    def compose_note_metadata(
        self,
        guide_note: NoteDocument,
        longform_note: NoteDocument,
        metadata: VideoMeta,
        *,
        prompt_name: str = "compose_note_metadata",
    ) -> NoteMetadata: ...
