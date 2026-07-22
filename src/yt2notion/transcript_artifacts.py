"""Typed transcript-only results and Markdown rendering."""

from __future__ import annotations

from dataclasses import dataclass
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
    audio_path: Path
    transcripts_path: Path
    transcript_markdown_path: Path

    def to_dict(self) -> dict:
        """Return a JSON-serializable summary for CLI and agent wrappers."""
        return {
            "video_id": self.metadata.video_id,
            "title": self.metadata.title,
            "channel": self.metadata.channel,
            "url": self.metadata.url,
            "workspace_dir": str(self.workspace.dir),
            "video_path": str(self.video_path) if self.video_path else None,
            "audio_path": str(self.audio_path),
            "transcripts_path": str(self.transcripts_path),
            "transcript_markdown_path": str(self.transcript_markdown_path),
        }


def render_media_transcript_markdown(
    metadata: VideoMeta,
    transcript_segments: list[dict],
    asr_backend: str,
) -> str:
    """Render a readable Markdown transcript with source metadata."""
    lines = [
        f"# Transcript: {metadata.title}",
        "",
        f"- Channel: {metadata.channel}",
        f"- URL: {metadata.url}",
        f"- ASR backend: {asr_backend}",
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


def render_reviewed_transcript_markdown(
    metadata: VideoMeta,
    transcript_segments: list[dict],
) -> str:
    """Render the legacy reviewed-transcript Markdown format."""
    lines = [f"## 逐字稿：{metadata.title}", ""]
    for segment in transcript_segments:
        start = int(segment.get("start_seconds", 0))
        lines.append(f"### [{seconds_to_display(start)}] {str(segment.get('title', '')).strip()}")
        lines.append("")
        lines.append(str(segment.get("text", "")).strip())
        lines.append("")
    return "\n".join(lines).strip()
