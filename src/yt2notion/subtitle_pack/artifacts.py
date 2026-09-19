"""Persistence and serialization helpers for bilingual subtitle artifacts."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.prompts import load_prompt

if TYPE_CHECKING:
    from yt2notion.subtitle_pack.models import BilingualCue


def prompt_fingerprint(name: str) -> str:
    """Return the stable fingerprint of a prompt template."""
    return hashlib.sha256(load_prompt(name).encode()).hexdigest()


def fingerprint(payload: object) -> str:
    """Return a stable JSON fingerprint for checkpoint identities."""
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode()).hexdigest()


def write_json(path: Path, payload: object) -> None:
    """Write a human-readable UTF-8 JSON artifact."""
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_subtitle_artifacts(
    workspace_dir: Path,
    package: dict[str, object],
    report: dict[str, object],
    cues: Sequence[BilingualCue],
) -> tuple[Path, Path, Path]:
    """Write the browser package, bilingual SRT, and quality report."""
    package_path = workspace_dir / "bilingual_subtitles.json"
    srt_path = workspace_dir / "bilingual_subtitles.srt"
    report_path = workspace_dir / "subtitle_quality_report.json"
    write_json(package_path, package)
    srt_path.write_text(render_srt(cues), encoding="utf-8")
    write_json(report_path, report)
    return package_path, srt_path, report_path


def render_srt(cues: Sequence[BilingualCue]) -> str:
    """Render bilingual cues as source and translation lines in SRT format."""
    blocks = []
    for index, cue in enumerate(cues, start=1):
        blocks.append(
            f"{index}\n{_srt_timestamp(cue.start_ms)} --> {_srt_timestamp(cue.end_ms)}\n"
            f"{cue.source_text}\n{cue.translated_text}"
        )
    return "\n\n".join(blocks) + "\n"


def _srt_timestamp(milliseconds: int) -> str:
    hours, remainder = divmod(milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    seconds, millis = divmod(remainder, 1_000)
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"
