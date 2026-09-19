"""Typed domain contracts shared by yt2notion pipelines."""

from __future__ import annotations

from dataclasses import dataclass

Seconds = int | float


def _validate_timeline(start_seconds: Seconds, end_seconds: Seconds, label: str) -> None:
    if isinstance(start_seconds, bool) or not isinstance(start_seconds, int | float):
        raise ValueError(f"{label} start_seconds must be a number")
    if isinstance(end_seconds, bool) or not isinstance(end_seconds, int | float):
        raise ValueError(f"{label} end_seconds must be a number")
    if start_seconds < 0:
        raise ValueError(f"{label} starts before zero")
    if end_seconds < start_seconds:
        raise ValueError(f"{label} ends before it starts")


@dataclass(frozen=True)
class SegmentSpec:
    """A structural chapter or ASR work interval without transcript text."""

    title: str
    start_seconds: Seconds
    end_seconds: Seconds
    parent_title: str | None = None

    def __post_init__(self) -> None:
        _validate_timeline(self.start_seconds, self.end_seconds, "segment")


@dataclass(frozen=True)
class TranscriptSegment:
    """A reading/review unit which may aggregate one or more timeline cues."""

    title: str
    start_seconds: Seconds
    end_seconds: Seconds
    text: str
    source: str

    def __post_init__(self) -> None:
        _validate_timeline(self.start_seconds, self.end_seconds, "transcript segment")
