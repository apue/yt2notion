"""Transcriber Protocol shared across ASR backends."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from yt2notion.process import SubtitleEntry


class Transcriber(Protocol):
    """Protocol for audio transcription backends."""

    max_upload_bytes: int | None  # None means no per-file size limit

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> list[SubtitleEntry]:
        """Transcribe audio file to timestamped subtitle entries."""
        ...
