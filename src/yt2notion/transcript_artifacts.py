"""Typed transcript-only results and Markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.process import seconds_to_display

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace


@dataclass
class MediaTranscribeResult:
    """Artifacts produced by the standalone transcription workflow."""

    metadata: VideoMeta
    workspace: Workspace
    video_path: Path | None
    audio_path: Path | None
    transcripts_path: Path
    transcript_markdown_path: Path
    timings_seconds: dict[str, float] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Return a JSON-serializable CLI summary."""
        return {
            "video_id": self.metadata.video_id,
            "title": self.metadata.title,
            "channel": self.metadata.channel,
            "url": self.metadata.url,
            "workspace_dir": str(self.workspace.dir),
            "video_path": str(self.video_path) if self.video_path else None,
            "audio_path": str(self.audio_path) if self.audio_path else None,
            "transcripts_path": str(self.transcripts_path),
            "transcript_markdown_path": str(self.transcript_markdown_path),
            "timings_seconds": self.timings_seconds,
        }


def render_media_transcript_markdown(
    metadata: VideoMeta,
    transcript_segments: list[dict],
    transcript_source: str,
) -> str:
    """Render a readable Markdown transcript with source metadata."""
    lines = [
        f"# Transcript: {metadata.title}",
        "",
        f"- Channel: {metadata.channel}",
        f"- URL: {metadata.url}",
        f"- Transcript source: {transcript_source}",
        "",
    ]
    for segment in transcript_segments:
        start = int(segment.get("start_seconds", 0))
        title = str(segment.get("title", "")).strip() or "Segment"
        text = str(segment.get("text", "")).strip()
        lines.extend(
            [
                f"## [{seconds_to_display(start)}] {title}",
                "",
                text,
                "",
            ]
        )
    return "\n".join(lines).strip() + "\n"


def resolve_transcript_source(transcript_segments: list[dict], asr_backend: str) -> str:
    """Describe subtitle origins directly and expand generic ASR attribution."""
    sources = list(
        dict.fromkeys(
            str(segment.get("source", "")).strip()
            for segment in transcript_segments
            if str(segment.get("source", "")).strip()
        )
    )
    resolved = [asr_backend if source == "asr" else source for source in sources]
    return ", ".join(resolved) or asr_backend
