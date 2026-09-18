"""Deterministic validation for subtitle sources and model responses."""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from yt2notion.subtitle_pack.models import BilingualCue, SourceCue


class SubtitlePackError(ValueError):
    """Raised when source or model output violates the subtitle contract."""


def validate_source_cues(cues: Sequence[SourceCue]) -> None:
    """Require a non-empty, ordered source timeline with valid cue ranges."""
    if not cues:
        raise SubtitlePackError("no timed source cues were produced")
    previous_start = -1
    for cue in cues:
        if cue.start_ms < 0 or cue.end_ms <= cue.start_ms:
            raise SubtitlePackError(f"invalid timing for {cue.id}")
        if cue.start_ms < previous_start:
            raise SubtitlePackError("source cues are not ordered by start time")
        previous_start = cue.start_ms


def parse_generated(
    records: object, owned: Sequence[SourceCue], source_kind: str
) -> list[BilingualCue]:
    """Parse generated cues while enforcing exact IDs and immutable source timing."""
    if not isinstance(records, list):
        raise SubtitlePackError("generation response must be a JSON array")
    expected_ids = [cue.id for cue in owned]
    actual_ids = [record.get("id") for record in records if isinstance(record, dict)]
    if actual_ids != expected_ids or len(records) != len(owned):
        raise SubtitlePackError(
            "generation IDs must exactly match source order: "
            f"expected {expected_ids}, got {actual_ids}"
        )
    result: list[BilingualCue] = []
    for cue, record in zip(owned, records, strict=True):
        source_text = record.get("source_text")
        translated_text = record.get("translated_text")
        if not isinstance(source_text, str) or not source_text.strip():
            raise SubtitlePackError(f"empty source_text for {cue.id}")
        if not isinstance(translated_text, str) or not translated_text.strip():
            raise SubtitlePackError(f"empty translated_text for {cue.id}")
        if source_kind == "manual_subtitle" and source_text.strip() != cue.original_text:
            raise SubtitlePackError(f"manual subtitle source text was changed for {cue.id}")
        result.append(
            BilingualCue(
                id=cue.id,
                start_ms=cue.start_ms,
                end_ms=cue.end_ms,
                original_text=cue.original_text,
                source_text=source_text.strip(),
                translated_text=translated_text.strip(),
            )
        )
    return result


def validate_bilingual(
    source: Sequence[SourceCue],
    generated: Sequence[BilingualCue],
    semantic_issues: list[dict[str, str]],
    *,
    schema_version: int,
) -> dict[str, object]:
    """Validate final cue coverage and return the deterministic quality report."""
    expected = [cue.id for cue in source]
    actual = [cue.id for cue in generated]
    if expected != actual:
        raise SubtitlePackError("final cue coverage or order differs from source")
    for source_cue, generated_cue in zip(source, generated, strict=True):
        if (source_cue.start_ms, source_cue.end_ms) != (
            generated_cue.start_ms,
            generated_cue.end_ms,
        ):
            raise SubtitlePackError(f"timing changed for {source_cue.id}")
    return {
        "schema_version": schema_version,
        "passed": not semantic_issues,
        "deterministic_checks": {
            "cue_count": len(source),
            "ordered_id_coverage": True,
            "timeline_unchanged": True,
            "nonempty_source_and_translation": True,
        },
        "semantic_issues": semantic_issues,
    }


def parse_json_object(raw: str, label: str) -> dict[str, object]:
    """Parse a possibly fenced JSON object from a model response."""
    payload = _parse_json(raw, label)
    if not isinstance(payload, dict):
        raise SubtitlePackError(f"{label} response must be a JSON object")
    return payload


def parse_json_array(raw: str, label: str) -> list[object]:
    """Parse a possibly fenced JSON array from a model response."""
    payload = _parse_json(raw, label)
    if not isinstance(payload, list):
        raise SubtitlePackError(f"{label} response must be a JSON array")
    return payload


def _parse_json(raw: str, label: str) -> object:
    text = raw.strip()
    fenced = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise SubtitlePackError(f"{label} response is not valid JSON") from exc
