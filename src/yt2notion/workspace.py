"""Workspace directory management for pipeline step artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt2notion.models.base import ChineseContent, EntityResult, VideoMeta

# Step name → output artifact filename
_STEP_ARTIFACTS: dict[str, str] = {
    "download": "metadata.json",
    "segment": "segments.json",
    "transcribe": "transcripts.json",
    "review": "reviewed.json",
    "extract": "entities.json",
    "summarize": "summary.json",
}
_ASR_FALLBACK_MARKER = "asr_fallback_used.json"

STEPS = ("download", "segment", "transcribe", "review", "extract", "summarize")


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

    # --- Entities ---

    def save_entities(self, result: EntityResult) -> None:
        from dataclasses import asdict

        self._write_json("entities.json", asdict(result))

    def load_entities(self) -> EntityResult | None:
        d = self._read_json("entities.json")
        if d is None:
            return None
        from yt2notion.models.base import Entity, EntityResult

        entities = [
            Entity(
                name=e["name"],
                type=e["type"],
                attributes=e.get("attributes", {}),
                linkable=e.get("linkable", True),
            )
            for e in d.get("entities", [])
        ]
        return EntityResult(
            domain=d.get("domain", ""),
            is_entity_centric=d.get("is_entity_centric", False),
            entity_types=d.get("entity_types", []),
            entities=entities,
            relations=d.get("relations", []),
        )

    # --- Summary ---

    def save_summary(self, content: ChineseContent) -> None:
        d = {
            "overview": content.overview,
            "key_points": content.key_points,
            "tags": content.tags,
            "fun_facts": content.fun_facts,
            "raw_markdown": content.raw_markdown,
            "mindmap": content.mindmap,
        }
        self._write_json("summary.json", d)

    # --- Failure tracking ---

    def save_failure(
        self,
        url: str,
        step: str,
        error: Exception | str,
        *,
        retries_exhausted: bool,
    ) -> None:
        """Persist structured failure details for the current workspace."""
        failure = {
            "url": url,
            "step": step,
            "error": str(error),
            "timestamp": datetime.now().astimezone().isoformat(timespec="seconds"),
            "retries_exhausted": retries_exhausted,
        }
        self._write_json("failed.json", failure)

    def load_failure(self) -> dict | None:
        """Load the last recorded failure, if any."""
        return self._read_json("failed.json")

    def clear_failure(self) -> None:
        """Remove any previous failure marker from the workspace."""
        path = self.dir / "failed.json"
        if path.exists():
            path.unlink()

    # --- ASR fallback / transcribe cleanup ---

    def discard_transcribe_artifacts(self, audio_path: Path | None = None) -> None:
        """Remove transcribe-stage artifacts so ASR can rerun cleanly."""
        transcript_path = self.dir / "transcripts.json"
        if transcript_path.exists():
            transcript_path.unlink()

        dirs_to_remove: set[Path] = {
            self.dir / "segments",
            self.dir / "full_audio_chunks",
        }
        dirs_to_remove.update(self.dir.glob("segment_*_chunks"))

        if audio_path is not None:
            audio_parent = audio_path.parent
            dirs_to_remove.add(audio_parent / "segments")
            dirs_to_remove.add(audio_parent / "full_audio_chunks")
            dirs_to_remove.update(audio_parent.glob("segment_*_chunks"))

        for path in dirs_to_remove:
            if path.exists():
                shutil.rmtree(path, ignore_errors=True)

    def mark_asr_fallback_used(self) -> None:
        """Persist that this workspace used ASR fallback."""
        self._write_json(_ASR_FALLBACK_MARKER, {"used": True})

    def clear_asr_fallback_used(self) -> None:
        """Clear persisted ASR fallback marker for a fresh transcribe execution."""
        path = self.dir / _ASR_FALLBACK_MARKER
        if path.exists():
            path.unlink()

    def asr_fallback_used(self) -> bool:
        """Return whether this workspace used ASR fallback."""
        payload = self._read_json(_ASR_FALLBACK_MARKER)
        if not isinstance(payload, dict):
            return False
        return bool(payload.get("used", False))

    # --- Internal helpers ---

    def _write_json(self, filename: str, data: object) -> None:
        path = self.dir / filename
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _read_json(self, filename: str) -> object | None:
        path = self.dir / filename
        if not path.exists():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
