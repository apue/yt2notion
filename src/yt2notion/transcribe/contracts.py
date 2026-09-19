"""Typed contracts and JSON codecs for resumable transcription artifacts."""

from __future__ import annotations

from dataclasses import dataclass

from yt2notion.domain import SegmentSpec


@dataclass
class TranscribeChunk:
    """One durable unit in a transcription plan."""

    chunk_id: str
    title: str
    start_seconds: float
    end_seconds: float
    audio_relpath: str
    preferred_backend: str
    segment_index: int | None = None

    def __post_init__(self) -> None:
        _validate_timeline(self.start_seconds, self.end_seconds, "transcribe chunk")
        if self.segment_index is not None and self.segment_index < 0:
            raise ValueError("transcribe chunk segment_index must not be negative")

    def as_segment(self) -> SegmentSpec:
        """Return the timeline-only view used by audio splitting."""
        return SegmentSpec(self.title, self.start_seconds, self.end_seconds)


@dataclass
class TranscribeChunkState:
    """Mutable resume state for one planned chunk."""

    chunk_id: str
    status: str
    backend_used: str | None
    result_relpath: str | None
    attempts: int
    updated_at: str

    def __post_init__(self) -> None:
        if self.attempts < 0:
            raise ValueError("transcribe chunk attempts must not be negative")


@dataclass
class TranscribeState:
    """Durable state for a batched transcription job."""

    version: int
    job_mode: str
    status: str
    next_attempt_at: str | None
    last_error: str | None
    defer_reason: str | None
    ash_defer_count: int
    chunks: list[TranscribeChunkState]

    def __post_init__(self) -> None:
        if self.ash_defer_count < 0:
            raise ValueError("transcribe ash_defer_count must not be negative")


@dataclass(frozen=True)
class ChunkTranscriptEntry:
    """One provider transcript entry persisted for a chunk."""

    start_seconds: float
    end_seconds: float
    text: str
    source: str = "asr"

    def __post_init__(self) -> None:
        _validate_timeline(self.start_seconds, self.end_seconds, "chunk transcript entry")


def encode_transcribe_plan(plan: list[TranscribeChunk]) -> list[dict[str, object]]:
    """Encode the unchanged transcribe_plan.json schema."""
    payload: list[dict[str, object]] = []
    for chunk in plan:
        record: dict[str, object] = {
            "chunk_id": chunk.chunk_id,
            "title": chunk.title,
            "start_seconds": chunk.start_seconds,
            "end_seconds": chunk.end_seconds,
            "audio_relpath": chunk.audio_relpath,
            "preferred_backend": chunk.preferred_backend,
        }
        if chunk.segment_index is not None:
            record["segment_index"] = chunk.segment_index
        payload.append(record)
    return payload


def decode_transcribe_plan(payload: object) -> list[TranscribeChunk]:
    """Decode and validate transcribe_plan.json."""
    records = _records(payload, "transcribe_plan.json")
    return [
        TranscribeChunk(
            chunk_id=_text(record, "chunk_id"),
            title=_text(record, "title"),
            start_seconds=_number(record, "start_seconds"),
            end_seconds=_number(record, "end_seconds"),
            audio_relpath=_text(record, "audio_relpath"),
            preferred_backend=_text(record, "preferred_backend"),
            segment_index=_optional_int(record, "segment_index"),
        )
        for record in records
    ]


def encode_transcribe_state(state: TranscribeState) -> dict[str, object]:
    """Encode the unchanged transcribe_state.json schema."""
    return {
        "version": state.version,
        "job_mode": state.job_mode,
        "status": state.status,
        "next_attempt_at": state.next_attempt_at,
        "last_error": state.last_error,
        "defer_reason": state.defer_reason,
        "ash_defer_count": state.ash_defer_count,
        "chunks": [
            {
                "chunk_id": chunk.chunk_id,
                "status": chunk.status,
                "backend_used": chunk.backend_used,
                "result_relpath": chunk.result_relpath,
                "attempts": chunk.attempts,
                "updated_at": chunk.updated_at,
            }
            for chunk in state.chunks
        ],
    }


def decode_transcribe_state(payload: object) -> TranscribeState:
    """Decode and validate transcribe_state.json."""
    if not isinstance(payload, dict):
        raise ValueError("Invalid transcribe_state.json: must be an object")
    chunks = _records(payload.get("chunks"), "transcribe_state.json chunks")
    return TranscribeState(
        version=_integer(payload, "version"),
        job_mode=_text(payload, "job_mode"),
        status=_text(payload, "status"),
        next_attempt_at=_optional_text(payload, "next_attempt_at"),
        last_error=_optional_text(payload, "last_error"),
        defer_reason=_optional_text(payload, "defer_reason"),
        ash_defer_count=_integer(payload, "ash_defer_count"),
        chunks=[
            TranscribeChunkState(
                chunk_id=_text(record, "chunk_id"),
                status=_text(record, "status"),
                backend_used=_optional_text(record, "backend_used"),
                result_relpath=_optional_text(record, "result_relpath"),
                attempts=_integer(record, "attempts"),
                updated_at=_text(record, "updated_at"),
            )
            for record in chunks
        ],
    )


def encode_chunk_entries(entries: list[ChunkTranscriptEntry]) -> list[dict[str, object]]:
    """Encode the unchanged transcribe chunk result schema."""
    return [
        {
            "start_seconds": entry.start_seconds,
            "end_seconds": entry.end_seconds,
            "text": entry.text,
            "source": entry.source,
        }
        for entry in entries
    ]


def decode_chunk_entries(payload: object) -> list[ChunkTranscriptEntry]:
    """Decode and validate one transcribe chunk result."""
    return [
        ChunkTranscriptEntry(
            start_seconds=_number(record, "start_seconds"),
            end_seconds=_number(record, "end_seconds"),
            text=_text(record, "text", allow_empty=True),
            source=_text(record, "source"),
        )
        for record in _records(payload, "transcribe chunk result")
    ]


def _records(payload: object, artifact: str) -> list[dict[str, object]]:
    if not isinstance(payload, list) or not all(isinstance(item, dict) for item in payload):
        raise ValueError(f"Invalid {artifact}: must be a list of objects")
    return payload


def _text(record: dict[str, object], field: str, *, allow_empty: bool = False) -> str:
    value = record.get(field)
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"Invalid field {field}: must be text")
    return value


def _optional_text(record: dict[str, object], field: str) -> str | None:
    value = record.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"Invalid field {field}: must be text or null")
    return value


def _number(record: dict[str, object], field: str) -> float:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise ValueError(f"Invalid field {field}: must be a number")
    return float(value)


def _integer(record: dict[str, object], field: str) -> int:
    value = record.get(field)
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid field {field}: must be an integer")
    return value


def _optional_int(record: dict[str, object], field: str) -> int | None:
    value = record.get(field)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"Invalid field {field}: must be an integer")
    return value


def _validate_timeline(start_seconds: float, end_seconds: float, label: str) -> None:
    if start_seconds < 0:
        raise ValueError(f"{label} starts before zero")
    if end_seconds < start_seconds:
        raise ValueError(f"{label} ends before it starts")
