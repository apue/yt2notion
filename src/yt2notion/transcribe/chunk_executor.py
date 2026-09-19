"""Provider execution, quota fallback, and upload subdivision for ASR chunks."""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import typer

from yt2notion.process import SubtitleEntry, seconds_to_display
from yt2notion.runtime import provider_call
from yt2notion.transcribe.audio_plan import (
    MIN_ASR_UPLOAD_CHUNK_SECONDS,
    build_segment_subchunks,
    rebase_chunk_entries,
    resolve_chunk_audio_path,
    resolve_full_audio_asr_chunk_seconds,
    resolve_upload_budget_chunk_seconds,
    transcriber_max_upload_bytes,
)
from yt2notion.transcribe.base import Transcriber
from yt2notion.transcribe.checkpoint import (
    chunk_state,
    clear_wait_state,
    mark_chunk_completed,
    mark_chunk_payload_missing,
    mark_hourly_wait,
    now,
    switch_remaining_chunks_to_backend,
)

if TYPE_CHECKING:
    from yt2notion.domain import SegmentSpec
    from yt2notion.transcribe.contracts import TranscribeChunk, TranscribeState
    from yt2notion.workspace import Workspace

ProgressEvent: TypeAlias = Literal[
    "started",
    "completed",
    "skipped",
    "failed",
    "chunk_started",
    "chunk_completed",
    "hourly_wait",
    "daily_fallback_switch",
]
ProgressCallback: TypeAlias = Callable[[str, ProgressEvent, str | None], None]
TranscriberFactory: TypeAlias = Callable[[], Transcriber | None]


def execute_chunk_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    plan: list[TranscribeChunk],
    state: TranscribeState,
    config: dict,
    primary_backend: str,
    transcriber: Transcriber,
    fallback_backend: str | None,
    fallback_transcriber_factory: TranscriberFactory | None,
    language: str | None,
    verbose: bool,
    progress_callback: ProgressCallback | None = None,
) -> None:
    """Execute a durable chunk plan with quota-aware resume and fallback."""
    from yt2notion.transcribe.errors import (
        TranscriptionDailyLimitError,
        TranscriptionHourlyLimitError,
    )

    configured_chunk_seconds = resolve_full_audio_asr_chunk_seconds(config)
    for index, chunk in enumerate(plan):
        chunk_id = chunk.chunk_id
        current = chunk_state(state, chunk_id)
        if current.status.startswith("completed_"):
            if ws.load_transcribe_chunk_result(chunk_id) is None:
                mark_chunk_payload_missing(state, chunk_id)
                ws.save_transcribe_state(state)
            else:
                continue

        if state.status == "waiting_ash" and state.next_attempt_at:
            wait_target = state.next_attempt_at
            retry_after_seconds = max(
                0.0, (datetime.fromisoformat(wait_target) - now()).total_seconds()
            )
            _emit_progress(
                progress_callback,
                "transcribe",
                "hourly_wait",
                _progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=chunk.preferred_backend or primary_backend,
                    retry_after_seconds=round(retry_after_seconds, 3),
                    next_attempt_at=wait_target,
                    resumed_from_state=True,
                    ash_defer_count=state.ash_defer_count,
                ),
            )
            _wait_until_retryable_time(state.next_attempt_at)
            clear_wait_state(state)
            ws.save_transcribe_state(state)

        while True:
            backend = chunk.preferred_backend or primary_backend
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_started",
                _progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    attempt=current.attempts + 1,
                ),
            )
            active_transcriber = _resolve_transcriber(
                backend=backend,
                primary_backend=primary_backend,
                primary_transcriber=transcriber,
                fallback_backend=fallback_backend,
                fallback_transcriber_factory=fallback_transcriber_factory,
            )
            chunk_file = resolve_chunk_audio_path(ws, chunk.audio_relpath)
            try:
                entries = _transcribe_entries_with_byte_budget(
                    audio_path=audio_path,
                    segment=chunk,
                    segment_file=chunk_file,
                    transcriber=active_transcriber,
                    language=language,
                    configured_chunk_seconds=configured_chunk_seconds,
                    verbose=verbose,
                    should_rebase=chunk.segment_index is None,
                )
            except TranscriptionHourlyLimitError as exc:
                mark_hourly_wait(state, chunk_id, exc)
                ws.save_transcribe_state(state)
                _emit_progress(
                    progress_callback,
                    "transcribe",
                    "hourly_wait",
                    _progress_message(
                        chunk,
                        index=index,
                        total=len(plan),
                        backend=backend,
                        retry_after_seconds=round(float(exc.retry_after_seconds), 3),
                        next_attempt_at=state.next_attempt_at,
                        resumed_from_state=False,
                        ash_defer_count=state.ash_defer_count,
                    ),
                )
                _wait_until_retryable_time(state.next_attempt_at)
                continue
            except TranscriptionDailyLimitError as exc:
                if backend != primary_backend:
                    raise
                fallback = (
                    fallback_transcriber_factory()
                    if fallback_transcriber_factory is not None
                    else None
                )
                if fallback_backend is None or fallback is None:
                    raise
                ws.mark_asr_fallback_used()
                affected_chunk_ids = [
                    pending.chunk_id
                    for pending in plan[index:]
                    if chunk_state(state, pending.chunk_id).status == "pending"
                ]
                switch_remaining_chunks_to_backend(
                    ws,
                    plan,
                    state,
                    start_index=index,
                    backend=fallback_backend,
                    error=exc,
                )
                _emit_progress(
                    progress_callback,
                    "transcribe",
                    "daily_fallback_switch",
                    _progress_message(
                        chunk,
                        index=index,
                        total=len(plan),
                        backend=backend,
                        fallback_backend=fallback_backend,
                        affected_chunk_ids=affected_chunk_ids,
                        affected_chunk_count=len(affected_chunk_ids),
                    ),
                )
                continue

            mark_chunk_completed(ws, state, chunk_id, backend_used=backend, entries=entries)
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_completed",
                _progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    entries_count=len(entries),
                    attempts=chunk_state(state, chunk_id).attempts,
                ),
            )
            break

    state.status = "completed"
    state.next_attempt_at = None
    state.defer_reason = None
    state.last_error = None
    ws.save_transcribe_state(state)


def _emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(step, event, message)


def _progress_message(
    chunk: TranscribeChunk,
    *,
    index: int,
    total: int,
    backend: str,
    **extra: object,
) -> str:
    payload: dict[str, object] = {
        "chunk_id": chunk.chunk_id,
        "chunk_index": index + 1,
        "chunk_total": total,
        "title": chunk.title,
        "start_seconds": chunk.start_seconds,
        "end_seconds": chunk.end_seconds,
        "start_label": seconds_to_display(chunk.start_seconds),
        "end_label": seconds_to_display(chunk.end_seconds),
        "backend": backend,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _wait_until_retryable_time(next_attempt_at: str | None) -> None:
    if not next_attempt_at:
        return
    target = datetime.fromisoformat(next_attempt_at)
    while True:
        remaining = (target - now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60.0))


def _resolve_transcriber(
    *,
    backend: str,
    primary_backend: str,
    primary_transcriber: Transcriber,
    fallback_backend: str | None,
    fallback_transcriber_factory: TranscriberFactory | None,
) -> Transcriber:
    from yt2notion.transcribe.errors import TranscriptionError

    if backend == primary_backend:
        return primary_transcriber
    if backend == fallback_backend and fallback_transcriber_factory is not None:
        resolved = fallback_transcriber_factory()
        if resolved is not None:
            return resolved
    raise TranscriptionError(f"No transcriber configured for backend {backend!r}")


def _transcribe_entries_with_byte_budget(
    *,
    audio_path: Path,
    segment: SegmentSpec | TranscribeChunk,
    segment_file: Path,
    transcriber: Transcriber,
    language: str | None,
    configured_chunk_seconds: int,
    verbose: bool,
    should_rebase: bool = False,
) -> list[SubtitleEntry]:
    from yt2notion.audio import split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    max_upload_bytes = transcriber_max_upload_bytes(transcriber)
    segment_duration = segment.end_seconds - segment.start_seconds
    segment_size = segment_file.stat().st_size if segment_file.exists() else 0
    if max_upload_bytes is not None and segment_file.exists() and segment_size > max_upload_bytes:
        if segment_duration <= MIN_ASR_UPLOAD_CHUNK_SECONDS:
            raise TranscriptionError(
                f"ASR chunk {segment_file.name} ({segment_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )

        chunk_seconds = resolve_upload_budget_chunk_seconds(
            segment_duration,
            file_size_bytes=segment_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )
        if chunk_seconds >= segment_duration:
            raise TranscriptionError(
                f"ASR chunk {segment_file.name} ({segment_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}); cannot subdivide further."
            )
        subchunks = build_segment_subchunks(segment, chunk_seconds)
        if verbose:
            typer.echo(
                "    Segment exceeds upload budget; subdividing "
                f"into {len(subchunks)} chunk(s) (~{chunk_seconds}s)"
            )
        subchunk_dir = segment_file.parent / f"{segment_file.stem}_chunks"
        subchunk_files = split_audio(audio_path, subchunks, subchunk_dir)
        rebased_entries: list[SubtitleEntry] = []
        for subchunk, subchunk_file in zip(subchunks, subchunk_files, strict=True):
            rebased_entries.extend(
                _transcribe_entries_with_byte_budget(
                    audio_path=audio_path,
                    segment=subchunk,
                    segment_file=subchunk_file,
                    transcriber=transcriber,
                    language=language,
                    configured_chunk_seconds=configured_chunk_seconds,
                    verbose=verbose,
                    should_rebase=True,
                )
            )
        return rebased_entries

    with provider_call("asr.transcribe"):
        entries = transcriber.transcribe(segment_file, language=language)
    if should_rebase:
        return rebase_chunk_entries(entries, segment)
    return entries
