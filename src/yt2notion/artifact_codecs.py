"""Validated JSON codecs for stable workspace artifact schemas."""

from __future__ import annotations

from collections.abc import Sequence

from yt2notion.domain import SegmentSpec, TranscriptSegment


def decode_segment_specs(payload: object) -> tuple[SegmentSpec, ...]:
    """Decode the existing segments.json schema into domain values."""
    records = _record_list(payload, "segments.json")
    result: list[SegmentSpec] = []
    for index, record in enumerate(records):
        result.append(
            SegmentSpec(
                title=_text(record, "title", index, "segments.json"),
                start_seconds=_seconds(record, "start_seconds", index, "segments.json"),
                end_seconds=_seconds(record, "end_seconds", index, "segments.json"),
                parent_title=_optional_text(record, "parent_title", index, "segments.json"),
            )
        )
    return tuple(result)


def encode_segment_specs(segments: Sequence[SegmentSpec]) -> list[dict[str, object]]:
    """Encode segment specs using the unchanged segments.json schema."""
    payload: list[dict[str, object]] = []
    for segment in segments:
        record: dict[str, object] = {
            "title": segment.title,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
        }
        if segment.parent_title is not None:
            record["parent_title"] = segment.parent_title
        payload.append(record)
    return payload


def decode_transcript_segments(payload: object) -> tuple[TranscriptSegment, ...]:
    """Decode transcripts.json/reviewed.json into validated domain values."""
    records = _record_list(payload, "transcript artifact")
    result: list[TranscriptSegment] = []
    for index, record in enumerate(records):
        result.append(
            TranscriptSegment(
                title=_text(record, "title", index, "transcript artifact"),
                start_seconds=_seconds(record, "start_seconds", index, "transcript artifact"),
                end_seconds=_seconds(record, "end_seconds", index, "transcript artifact"),
                text=_text(record, "text", index, "transcript artifact", allow_empty=True),
                source=_text(record, "source", index, "transcript artifact"),
            )
        )
    return tuple(result)


def encode_transcript_segments(
    segments: Sequence[TranscriptSegment],
) -> list[dict[str, object]]:
    """Encode transcript segments using the unchanged workspace JSON schema."""
    return [
        {
            "title": segment.title,
            "start_seconds": segment.start_seconds,
            "end_seconds": segment.end_seconds,
            "text": segment.text,
            "source": segment.source,
        }
        for segment in segments
    ]


def _record_list(payload: object, artifact: str) -> list[dict[str, object]]:
    if not isinstance(payload, list):
        raise ValueError(f"Invalid {artifact}: must be a list")
    if not all(isinstance(record, dict) for record in payload):
        raise ValueError(f"Invalid {artifact}: every item must be an object")
    return payload


def _text(
    record: dict[str, object],
    field: str,
    index: int,
    artifact: str,
    *,
    allow_empty: bool = False,
) -> str:
    value = record.get(field)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Invalid {artifact} item {index}: {field} must be text")
    return value


def _optional_text(record: dict[str, object], field: str, index: int, artifact: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid {artifact} item {index}: {field} must be text")
    return value


def _seconds(record: dict[str, object], field: str, index: int, artifact: str) -> int | float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Invalid {artifact} item {index}: {field} must be a number")
    return value
