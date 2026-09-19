"""Resumable transcription checkpoint state transitions."""

from __future__ import annotations

from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.process import SubtitleEntry
from yt2notion.transcribe.contracts import (
    ChunkTranscriptEntry,
    TranscribeChunk,
    TranscribeChunkState,
    TranscribeState,
)

if TYPE_CHECKING:
    from yt2notion.workspace import Workspace


def now() -> datetime:
    """Return the checkpoint clock value."""
    return datetime.now().astimezone()


def retry_timestamp(retry_after_seconds: float) -> str:
    """Return the persisted retry deadline."""
    return (now() + timedelta(seconds=max(0.0, retry_after_seconds))).isoformat(timespec="seconds")


def chunk_payload_from_entries(entries: list[SubtitleEntry]) -> list[ChunkTranscriptEntry]:
    """Convert provider entries to the durable chunk contract."""
    return [
        ChunkTranscriptEntry(
            start_seconds=entry.start_seconds,
            end_seconds=entry.end_seconds,
            text=entry.text,
        )
        for entry in entries
    ]


def entries_from_chunk_payload(payload: list[ChunkTranscriptEntry]) -> list[SubtitleEntry]:
    """Convert a durable chunk payload to processing entries."""
    return [
        SubtitleEntry(
            start_seconds=entry.start_seconds,
            end_seconds=entry.end_seconds,
            text=entry.text,
        )
        for entry in payload
    ]


def load_required_chunk_payload(
    ws: Workspace,
    chunk_id: str,
) -> list[ChunkTranscriptEntry]:
    """Load a completed chunk payload or fail the resumed job."""
    from yt2notion.transcribe.errors import TranscriptionError

    payload = ws.load_transcribe_chunk_result(chunk_id)
    if payload is None:
        raise TranscriptionError(f"Missing transcribe chunk result for {chunk_id}")
    return payload


def load_or_create_transcribe_state(
    ws: Workspace,
    plan: list[TranscribeChunk],
    *,
    job_mode: str,
) -> TranscribeState:
    """Load compatible state or initialize and reconcile it from chunk payloads."""
    state = ws.load_transcribe_state()
    if state is None or not _state_matches_plan(state, plan):
        state = _initial_state(plan, job_mode=job_mode)
    if _reconcile_from_chunk_results(ws, plan, state):
        ws.save_transcribe_state(state)
    return state


def chunk_state(state: TranscribeState, chunk_id: str) -> TranscribeChunkState:
    """Return mutable state for one planned chunk."""
    for chunk in state.chunks:
        if chunk.chunk_id == chunk_id:
            return chunk
    raise ValueError(f"Missing transcribe state for chunk {chunk_id!r}")


def clear_wait_state(state: TranscribeState) -> None:
    """Reset transient quota-wait state."""
    state.status = "running"
    state.next_attempt_at = None
    state.defer_reason = None
    state.last_error = None


def mark_hourly_wait(state: TranscribeState, chunk_id: str, error: Exception) -> None:
    """Persist an hourly quota wait for the current chunk."""
    chunk = chunk_state(state, chunk_id)
    chunk.attempts += 1
    chunk.updated_at = now().isoformat(timespec="seconds")
    state.status = "waiting_ash"
    state.next_attempt_at = retry_timestamp(getattr(error, "retry_after_seconds", 0))
    state.defer_reason = "ash"
    state.last_error = str(error)
    state.ash_defer_count += 1


def mark_chunk_payload_missing(state: TranscribeState, chunk_id: str) -> None:
    """Return a completed chunk with a missing payload to pending state."""
    chunk = chunk_state(state, chunk_id)
    state.status = "running"
    state.next_attempt_at = None
    state.defer_reason = None
    chunk.status = "pending"
    chunk.backend_used = None
    chunk.result_relpath = None
    chunk.updated_at = now().isoformat(timespec="seconds")


def mark_chunk_completed(
    ws: Workspace,
    state: TranscribeState,
    chunk_id: str,
    *,
    backend_used: str,
    entries: list[SubtitleEntry],
) -> None:
    """Atomically record a chunk payload and its completed state."""
    ws.save_transcribe_chunk_result(chunk_id, chunk_payload_from_entries(entries))
    chunk = chunk_state(state, chunk_id)
    chunk.attempts += 1
    chunk.backend_used = backend_used
    chunk.result_relpath = str(Path("transcribe_chunks") / f"{chunk_id}.json")
    chunk.status = f"completed_{backend_used}"
    chunk.updated_at = now().isoformat(timespec="seconds")
    clear_wait_state(state)
    ws.save_transcribe_state(state)


def switch_remaining_chunks_to_backend(
    ws: Workspace,
    plan: list[TranscribeChunk],
    state: TranscribeState,
    *,
    start_index: int,
    backend: str,
    error: Exception,
) -> None:
    """Persist a daily-quota fallback for remaining pending chunks."""
    for chunk in plan[start_index:]:
        current = chunk_state(state, chunk.chunk_id)
        if current.status == "pending":
            chunk.preferred_backend = backend
    state.job_mode = "remote_remaining"
    state.status = "running"
    state.next_attempt_at = None
    state.defer_reason = None
    state.last_error = str(error)
    ws.save_transcribe_plan(plan)
    ws.save_transcribe_state(state)


def describe_backend_outcome(ws: Workspace, *, default_backend: str) -> str:
    """Describe actual backend use from transcribe checkpoint state."""
    state = ws.load_transcribe_state()
    if state is None:
        return default_backend

    backends = [chunk.backend_used for chunk in state.chunks if chunk.backend_used is not None]
    if not backends:
        return default_backend

    unique = list(dict.fromkeys(backends))
    if len(unique) == 1:
        return unique[0]
    return "mixed: " + ", ".join(unique)


def _initial_state(plan: list[TranscribeChunk], *, job_mode: str) -> TranscribeState:
    timestamp = now().isoformat(timespec="seconds")
    return TranscribeState(
        version=1,
        job_mode=job_mode,
        status="running",
        next_attempt_at=None,
        last_error=None,
        defer_reason=None,
        ash_defer_count=0,
        chunks=[
            TranscribeChunkState(
                chunk_id=chunk.chunk_id,
                status="pending",
                backend_used=None,
                result_relpath=None,
                attempts=0,
                updated_at=timestamp,
            )
            for chunk in plan
        ],
    )


def _state_matches_plan(state: TranscribeState, plan: list[TranscribeChunk]) -> bool:
    if state.version != 1:
        return False
    return [chunk.chunk_id for chunk in state.chunks] == [chunk.chunk_id for chunk in plan]


def _reconcile_from_chunk_results(
    ws: Workspace,
    plan: list[TranscribeChunk],
    state: TranscribeState,
) -> bool:
    changed = False
    for chunk in plan:
        current = chunk_state(state, chunk.chunk_id)
        payload = ws.load_transcribe_chunk_result(chunk.chunk_id)
        if payload is None:
            if current.status.startswith("completed_"):
                mark_chunk_payload_missing(state, chunk.chunk_id)
                changed = True
            continue
        if current.status.startswith("completed_"):
            continue
        backend_used = current.backend_used or chunk.preferred_backend or "asr"
        current.backend_used = backend_used
        current.result_relpath = str(Path("transcribe_chunks") / f"{chunk.chunk_id}.json")
        current.status = f"completed_{backend_used}"
        current.updated_at = now().isoformat(timespec="seconds")
        changed = True
    return changed
