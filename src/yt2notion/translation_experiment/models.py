"""Typed contracts for translation experiments."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class SourceBlock:
    """One stable translation unit within a source chapter."""

    block_id: str
    source_text: str


@dataclass(frozen=True)
class SourceChapter:
    """One source chapter and its deterministic semantic blocks."""

    chapter_id: str
    title: str
    start_seconds: int
    end_seconds: int
    source_text: str
    blocks: tuple[SourceBlock, ...]


@dataclass(frozen=True)
class TranslationItem:
    """A generated translation tied to an exact source identifier."""

    source_id: str
    translation: str


@dataclass(frozen=True)
class CandidateCheckpoint:
    """Validated candidate content plus its original generation latency."""

    items: tuple[TranslationItem, ...]
    generation_seconds: float


@dataclass(frozen=True)
class TranslationExperimentResult:
    """Paths and timings produced by a completed experiment."""

    workspace_dir: Path
    experiment_dir: Path
    blind_review_path: Path
    answer_key_path: Path
    manifest_path: Path
    timings_seconds: dict[str, float]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable CLI payload."""
        payload = asdict(self)
        for key in (
            "workspace_dir",
            "experiment_dir",
            "blind_review_path",
            "answer_key_path",
            "manifest_path",
        ):
            payload[key] = str(payload[key])
        return payload
