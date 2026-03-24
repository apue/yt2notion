"""Workspace directory management for pipeline step artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, VideoMeta

# Step name → output artifact filename
_STEP_ARTIFACTS: dict[str, str] = {
    "download": "metadata.json",
    "segment": "segments.json",
    "transcribe": "transcripts.json",
    "review": "reviewed.json",
    "summarize": "summary.json",
}

STEPS = ("download", "segment", "transcribe", "review", "summarize")


class Workspace:
    """Manages a workspace directory for one pipeline run.

    Each step writes its output as a JSON file. The pipeline can resume
    from any step by loading the previous step's artifact.
    """

    def __init__(self, base_dir: Path, video_id: str) -> None:
        self.dir = base_dir / video_id
        self.dir.mkdir(parents=True, exist_ok=True)

    # --- Step tracking ---

    def step_done(self, step: str) -> bool:
        """Check if a step's output artifact exists."""
        filename = _STEP_ARTIFACTS.get(step, "")
        if not filename:
            return False
        return (self.dir / filename).exists()

    # --- Metadata ---

    def save_metadata(self, meta: VideoMeta) -> None:
        d = asdict(meta)
        self._write_json("metadata.json", d)

    def load_metadata(self) -> VideoMeta | None:
        d = self._read_json("metadata.json")
        if d is None:
            return None
        from yt2notion.models.base import Chapter, VideoMeta

        chapters = [
            Chapter(
                title=ch["title"],
                start_seconds=ch["start_seconds"],
                end_seconds=ch["end_seconds"],
            )
            for ch in d.get("chapters", [])
        ]
        return VideoMeta(
            video_id=d["video_id"],
            title=d["title"],
            channel=d["channel"],
            upload_date=d.get("upload_date", ""),
            url=d.get("url", ""),
            duration_seconds=d.get("duration_seconds", 0),
            chapters=chapters,
            description=d.get("description", ""),
            language=d.get("language", ""),
            subtitles_available=d.get("subtitles_available", False),
            series=d.get("series", ""),
        )

    # --- Media files ---

    def save_audio(self, src: Path) -> Path:
        """Copy audio file into workspace. Returns destination path."""
        dst = self.dir / f"audio{src.suffix}"
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    def save_subtitles(self, src: Path) -> Path:
        """Copy subtitle file into workspace. Returns destination path."""
        dst = self.dir / f"subtitles{src.suffix}"
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    @property
    def audio_path(self) -> Path | None:
        for ext in (".mp3", ".m4a", ".wav", ".opus", ".ogg"):
            p = self.dir / f"audio{ext}"
            if p.exists():
                return p
        return None

    @property
    def subtitle_path(self) -> Path | None:
        for ext in (".srt", ".vtt"):
            p = self.dir / f"subtitles{ext}"
            if p.exists():
                return p
        return None

    # --- Segments ---

    def save_segments(self, segments: list[dict]) -> None:
        self._write_json("segments.json", segments)

    def load_segments(self) -> list[dict] | None:
        return self._read_json("segments.json")

    # --- Transcripts ---

    def save_transcripts(self, transcripts: list[dict]) -> None:
        self._write_json("transcripts.json", transcripts)

    def load_transcripts(self) -> list[dict] | None:
        return self._read_json("transcripts.json")

    # --- Reviewed ---

    def save_reviewed(self, reviewed: list[dict]) -> None:
        self._write_json("reviewed.json", reviewed)

    def load_reviewed(self) -> list[dict] | None:
        return self._read_json("reviewed.json")

    # --- Summary ---

    def save_summary(self, content: ChineseContent) -> None:
        d = {
            "overview": content.overview,
            "key_points": content.key_points,
            "tags": content.tags,
            "raw_markdown": content.raw_markdown,
            "mindmap": content.mindmap,
        }
        self._write_json("summary.json", d)

    # --- Internal helpers ---

    def _write_json(self, filename: str, data: object) -> None:
        path = self.dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_json(self, filename: str) -> object | None:
        path = self.dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
