"""Workspace directory management for pipeline step artifacts."""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.models.base import (
    NOTE_VARIANT_GUIDE,
    NOTE_VARIANT_LONGFORM,
    NOTE_VARIANT_SOURCE,
)

if TYPE_CHECKING:
    from yt2notion.models.base import NoteBundle, VideoMeta

# Step name → output artifact filename
_STEP_ARTIFACTS: dict[str, str] = {
    "download": "metadata.json",
    "segment": "segments.json",
    "transcribe": "transcripts.json",
    "review": "reviewed.json",
    "summarize": "note_bundle.json",
}
_ASR_FALLBACK_MARKER = "asr_fallback_used.json"

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

    def save_video(self, src: Path) -> Path:
        """Copy video file into workspace. Returns destination path."""
        dst = self.dir / f"video{src.suffix}"
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    def discard_video_artifacts(self) -> None:
        """Remove saved video artifacts from this workspace."""
        for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
            path = self.dir / f"video{ext}"
            if path.exists():
                path.unlink()

    def save_subtitles(self, src: Path) -> Path:
        """Copy subtitle file into workspace. Returns destination path."""
        dst = self.dir / f"subtitles{src.suffix}"
        if src != dst:
            shutil.copy2(src, dst)
        return dst

    def save_subtitle_source(self, source: str) -> None:
        """Persist the subtitle origin marker for cleanup policy decisions."""
        self._write_json("subtitle_source.json", {"source": source})

    def load_subtitle_source(self) -> str | None:
        """Load the persisted subtitle origin marker, if present."""
        data = self._read_json("subtitle_source.json")
        if not isinstance(data, dict):
            return None
        source = data.get("source")
        return str(source) if source else None

    @property
    def audio_path(self) -> Path | None:
        for ext in (".mp3", ".m4a", ".wav", ".opus", ".ogg"):
            p = self.dir / f"audio{ext}"
            if p.exists():
                return p
        return None

    @property
    def video_path(self) -> Path | None:
        for ext in (".mp4", ".mkv", ".webm", ".mov", ".m4v"):
            p = self.dir / f"video{ext}"
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

    def save_transcribe_plan(self, plan: list[dict]) -> None:
        self._write_json("transcribe_plan.json", plan)

    def load_transcribe_plan(self) -> list[dict] | None:
        return self._read_json("transcribe_plan.json")

    def save_transcribe_state(self, state: dict) -> None:
        self._write_json("transcribe_state.json", state)

    def load_transcribe_state(self) -> dict | None:
        return self._read_json("transcribe_state.json")

    def save_transcribe_chunk_result(self, chunk_id: str, entries: list[dict]) -> None:
        chunk_dir = self.dir / "transcribe_chunks"
        chunk_dir.mkdir(parents=True, exist_ok=True)
        self._write_json(str(Path("transcribe_chunks") / f"{chunk_id}.json"), entries)

    def load_transcribe_chunk_result(self, chunk_id: str) -> list[dict] | None:
        return self._read_json(str(Path("transcribe_chunks") / f"{chunk_id}.json"))

    # --- Reviewed ---

    def save_reviewed(self, reviewed: list[dict]) -> None:
        self._write_json("reviewed.json", reviewed)

    def load_reviewed(self) -> list[dict] | None:
        return self._read_json("reviewed.json")

    # --- Note bundle ---

    def save_note_bundle(self, bundle: NoteBundle) -> None:
        """Persist a source/A/B note bundle as one workspace artifact."""
        _validate_note_bundle(bundle)
        self._write_json("note_bundle.json", asdict(bundle))

    def load_note_bundle(self) -> NoteBundle | None:
        """Load the persisted source/A/B note bundle, if present."""
        d = self._read_json("note_bundle.json")
        if d is None:
            return None
        from yt2notion.models.base import NoteBundle, NoteDocument

        source = NoteDocument(**d["source"])
        guide = NoteDocument(**d["guide"])
        longform = NoteDocument(**d["longform"])
        _validate_note_document(source, NOTE_VARIANT_SOURCE, "source")
        _validate_note_document(guide, NOTE_VARIANT_GUIDE, "guide")
        _validate_note_document(longform, NOTE_VARIANT_LONGFORM, "longform")
        if "stable_tags" not in d:
            raise ValueError("Invalid note_bundle.json: missing required field 'stable_tags'")
        if "source_topics" not in d:
            raise ValueError("Invalid note_bundle.json: missing required field 'source_topics'")

        return NoteBundle(
            source=source,
            guide=guide,
            longform=longform,
            stable_tags=d["stable_tags"],
            source_topics=d["source_topics"],
        )

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

        for filename in ("transcribe_plan.json", "transcribe_state.json"):
            path = self.dir / filename
            if path.exists():
                path.unlink()

        dirs_to_remove: set[Path] = {
            self.dir / "segments",
            self.dir / "full_audio_chunks",
            self.dir / "transcribe_chunks",
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


def _validate_note_document(note: object, expected_variant: str, label: str) -> None:
    """Reject persisted note bundles whose variants drift from their slot."""
    actual_variant = getattr(note, "variant", None)
    if actual_variant != expected_variant:
        raise ValueError(
            f"Invalid {label} note variant: expected {expected_variant!r}, got {actual_variant!r}"
        )


def _validate_note_bundle(bundle: object) -> None:
    """Validate note-bundle slot/variant alignment before persisting."""
    source = getattr(bundle, "source", None)
    guide = getattr(bundle, "guide", None)
    longform = getattr(bundle, "longform", None)
    _validate_note_document(source, NOTE_VARIANT_SOURCE, "source")
    _validate_note_document(guide, NOTE_VARIANT_GUIDE, "guide")
    _validate_note_document(longform, NOTE_VARIANT_LONGFORM, "longform")
