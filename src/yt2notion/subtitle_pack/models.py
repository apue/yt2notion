"""Stable subtitle-package data contracts."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass(frozen=True)
class SourceCue:
    """One immutable source timeline entry."""

    id: str
    start_ms: int
    end_ms: int
    original_text: str


@dataclass(frozen=True)
class BilingualCue:
    """One translated cue without LLM-owned timing fields."""

    id: str
    start_ms: int
    end_ms: int
    original_text: str
    source_text: str
    translated_text: str


@dataclass(frozen=True)
class SubtitlePackResult:
    """Local artifacts produced by the subtitle-pack use case."""

    workspace_dir: Path
    package_path: Path
    srt_path: Path
    context_path: Path
    quality_report_path: Path
    profile_path: Path
    cue_count: int
    source_kind: str
    quality_passed: bool = True

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable CLI result."""
        return {
            "workspace_dir": str(self.workspace_dir),
            "package_path": str(self.package_path),
            "srt_path": str(self.srt_path),
            "context_path": str(self.context_path),
            "quality_report_path": str(self.quality_report_path),
            "profile_path": str(self.profile_path),
            "cue_count": self.cue_count,
            "source_kind": self.source_kind,
            "quality_passed": self.quality_passed,
        }


def cue_dict(cue: SourceCue | BilingualCue) -> dict[str, object]:
    """Serialize either cue contract."""
    return asdict(cue)
