"""Shared transcription engine for subtitle/audio ASR lifecycle."""

from __future__ import annotations

import json
import math
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING, Literal, TypeAlias

import typer

from yt2notion.extract import ExtractionError
from yt2notion.process import SubtitleEntry, parse_subtitle_file, seconds_to_display
from yt2notion.transcribe.base import Transcriber

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

FULL_AUDIO_ASR_CHUNK_SECONDS = 300
MIN_ASR_UPLOAD_CHUNK_SECONDS = 30
ASR_CHUNK_PADDING_SECONDS = 0.5
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
ChunkResultPayload: TypeAlias = list[dict[str, object]]
TranscriberFactory: TypeAlias = Callable[[], Transcriber | None]
PrimaryTranscriberFactory: TypeAlias = Callable[[], Transcriber]


def _emit_progress(
    progress_callback: ProgressCallback | None,
    step: str,
    event: ProgressEvent,
    message: str | None = None,
) -> None:
    if progress_callback is not None:
        progress_callback(step, event, message)


class TranscriptionEngine:
    """Owns subtitle/audio transcription, chunk checkpoints, quota waits, and fallback."""

    def __init__(
        self,
        config: dict,
        *,
        primary_transcriber: Transcriber | None = None,
        primary_transcriber_factory: PrimaryTranscriberFactory | None = None,
        primary_backend: str | None = None,
        fallback_backend: str | None = None,
        fallback_transcriber_factory: TranscriberFactory | None = None,
    ) -> None:
        self.config = config
        asr_cfg = config.get("extract", {}).get("asr", {})
        self.primary_backend = primary_backend or str(asr_cfg.get("backend", "remote"))
        self.fallback_backend = (
            fallback_backend if fallback_backend is not None else asr_cfg.get("fallback_backend")
        )
        self._primary_transcriber = primary_transcriber
        self._primary_transcriber_factory = primary_transcriber_factory
        self._fallback_transcriber_factory = fallback_transcriber_factory

    def transcribe_workspace(
        self,
        ws: Workspace,
        metadata: VideoMeta,
        segments: list[dict],
        *,
        verbose: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict]:
        """Transcribe current workspace subtitles or audio into transcript segments."""
        if verbose:
            typer.echo("Transcribing...")

        sub_path = ws.subtitle_path
        audio_path = ws.audio_path

        if sub_path:
            subtitle_source = ws.load_subtitle_source() or "subtitle"
            return _transcribe_from_subtitles(
                sub_path,
                segments,
                metadata,
                self.config,
                verbose,
                source=subtitle_source,
            )
        if audio_path is None:
            raise ExtractionError("No subtitles or audio found in workspace")

        return self.transcribe_audio(
            audio_path,
            segments,
            metadata,
            ws,
            verbose=verbose,
            progress_callback=progress_callback,
        )

    def transcribe_audio(
        self,
        audio_path: Path,
        segments: list[dict],
        metadata: VideoMeta,
        ws: Workspace,
        *,
        verbose: bool = False,
        progress_callback: ProgressCallback | None = None,
    ) -> list[dict]:
        """Transcribe audio via the configured primary/fallback providers."""
        transcriber = self._primary_transcriber
        if transcriber is None:
            if self._primary_transcriber_factory is None:
                raise ValueError("TranscriptionEngine requires a primary Transcriber Adapter")
            transcriber = self._primary_transcriber_factory()
            self._primary_transcriber = transcriber

        fallback_factory = self._fallback_transcriber_factory
        if fallback_factory is None and self.fallback_backend:
            fallback_transcriber: Transcriber | None = None

            def _load_fallback_transcriber() -> Transcriber | None:
                nonlocal fallback_transcriber
                if fallback_transcriber is None:
                    from yt2notion.transcribe import create_fallback_transcriber

                    fallback_transcriber = create_fallback_transcriber(self.config)
                return fallback_transcriber

            fallback_factory = _load_fallback_transcriber

        return _transcribe_from_audio(
            audio_path,
            segments,
            metadata,
            self.config,
            ws,
            verbose,
            transcriber=transcriber,
            primary_backend=self.primary_backend,
            fallback_backend=self.fallback_backend,
            fallback_transcriber_factory=fallback_factory,
            progress_callback=progress_callback,
        )

    def backend_outcome(self, ws: Workspace) -> str:
        """Return the actual ASR backend usage recorded in checkpoint state."""
        return describe_backend_outcome(ws, default_backend=self.primary_backend)


def _current_time() -> datetime:
    return datetime.now().astimezone()


def _now() -> datetime:
    return _current_time()


def _iso_after_retry(retry_after_seconds: float) -> str:
    return (_now() + timedelta(seconds=max(0.0, retry_after_seconds))).isoformat(timespec="seconds")


def _wait_until_retryable_time(next_attempt_at: str | None, *, verbose: bool) -> None:
    if not next_attempt_at:
        return
    target = datetime.fromisoformat(next_attempt_at)
    while True:
        remaining = (target - _now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60.0))


def _chunk_payload_from_entries(entries: list[SubtitleEntry]) -> ChunkResultPayload:
    return [
        {
            "start_seconds": entry.start_seconds,
            "end_seconds": entry.end_seconds,
            "text": entry.text,
            "source": "asr",
        }
        for entry in entries
    ]


def _entries_from_chunk_payload(payload: ChunkResultPayload) -> list[SubtitleEntry]:
    return [
        SubtitleEntry(
            start_seconds=float(entry["start_seconds"]),
            end_seconds=float(entry["end_seconds"]),
            text=str(entry["text"]),
        )
        for entry in payload
    ]


def _chunk_audio_ref(ws: Workspace, path: Path) -> str:
    try:
        return str(path.relative_to(ws.dir))
    except ValueError:
        return str(path)


def _resolve_chunk_audio_path(ws: Workspace, audio_ref: str) -> Path:
    path = Path(audio_ref)
    if path.is_absolute():
        return path
    return ws.dir / path


def _transcribe_progress_message(
    chunk: dict,
    *,
    index: int,
    total: int,
    backend: str,
    **extra: object,
) -> str:
    payload: dict[str, object] = {
        "chunk_id": str(chunk["chunk_id"]),
        "chunk_index": index + 1,
        "chunk_total": total,
        "title": str(chunk.get("title", "")),
        "start_seconds": float(chunk["start_seconds"]),
        "end_seconds": float(chunk["end_seconds"]),
        "start_label": seconds_to_display(float(chunk["start_seconds"])),
        "end_label": seconds_to_display(float(chunk["end_seconds"])),
        "backend": backend,
    }
    payload.update(extra)
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def _initial_transcribe_state(plan: list[dict], *, job_mode: str) -> dict:
    timestamp = _now().isoformat(timespec="seconds")
    return {
        "version": 1,
        "job_mode": job_mode,
        "status": "running",
        "next_attempt_at": None,
        "last_error": None,
        "defer_reason": None,
        "ash_defer_count": 0,
        "chunks": [
            {
                "chunk_id": chunk["chunk_id"],
                "status": "pending",
                "backend_used": None,
                "result_relpath": None,
                "attempts": 0,
                "updated_at": timestamp,
            }
            for chunk in plan
        ],
    }


def _load_or_create_transcribe_state(ws: Workspace, plan: list[dict], *, job_mode: str) -> dict:
    state = ws.load_transcribe_state()
    if state is None or not _transcribe_state_matches_plan(state, plan):
        state = _initial_transcribe_state(plan, job_mode=job_mode)
    if _reconcile_transcribe_state_from_chunk_results(ws, plan, state):
        ws.save_transcribe_state(state)
    return state


def _chunk_state(state: dict, chunk_id: str) -> dict:
    for chunk in state.get("chunks", []):
        if chunk.get("chunk_id") == chunk_id:
            return chunk
    raise ValueError(f"Missing transcribe state for chunk {chunk_id!r}")


def _transcribe_state_matches_plan(state: dict, plan: list[dict]) -> bool:
    if not isinstance(state, dict):
        return False
    if state.get("version") != 1:
        return False
    state_chunk_ids = [chunk.get("chunk_id") for chunk in state.get("chunks", [])]
    plan_chunk_ids = [chunk.get("chunk_id") for chunk in plan]
    return state_chunk_ids == plan_chunk_ids


def _reconcile_transcribe_state_from_chunk_results(
    ws: Workspace, plan: list[dict], state: dict
) -> bool:
    changed = False
    for chunk in plan:
        chunk_id = str(chunk["chunk_id"])
        chunk_state = _chunk_state(state, chunk_id)
        payload = ws.load_transcribe_chunk_result(chunk_id)
        if payload is None:
            if str(chunk_state.get("status", "")).startswith("completed_"):
                _mark_chunk_payload_missing(state, chunk_id)
                changed = True
            continue
        if str(chunk_state.get("status", "")).startswith("completed_"):
            continue
        backend_used = str(chunk_state.get("backend_used") or chunk.get("preferred_backend", "asr"))
        chunk_state["backend_used"] = backend_used
        chunk_state["result_relpath"] = str(Path("transcribe_chunks") / f"{chunk_id}.json")
        chunk_state["status"] = f"completed_{backend_used}"
        chunk_state["updated_at"] = _now().isoformat(timespec="seconds")
        changed = True
    return changed


def _clear_wait_state(state: dict) -> None:
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = None


def _mark_hourly_wait(state: dict, chunk_id: str, error) -> None:
    chunk = _chunk_state(state, chunk_id)
    chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
    chunk["updated_at"] = _now().isoformat(timespec="seconds")
    state["status"] = "waiting_ash"
    state["next_attempt_at"] = _iso_after_retry(error.retry_after_seconds)
    state["defer_reason"] = "ash"
    state["last_error"] = str(error)
    state["ash_defer_count"] = int(state.get("ash_defer_count", 0)) + 1


def _mark_chunk_payload_missing(state: dict, chunk_id: str) -> None:
    chunk = _chunk_state(state, chunk_id)
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    chunk["status"] = "pending"
    chunk["backend_used"] = None
    chunk["result_relpath"] = None
    chunk["updated_at"] = _now().isoformat(timespec="seconds")


def _mark_chunk_completed(
    ws: Workspace,
    state: dict,
    chunk_id: str,
    *,
    backend_used: str,
    entries: list[SubtitleEntry],
) -> None:
    ws.save_transcribe_chunk_result(chunk_id, _chunk_payload_from_entries(entries))
    chunk = _chunk_state(state, chunk_id)
    chunk["attempts"] = int(chunk.get("attempts", 0)) + 1
    chunk["backend_used"] = backend_used
    chunk["result_relpath"] = str(Path("transcribe_chunks") / f"{chunk_id}.json")
    chunk["status"] = f"completed_{backend_used}"
    chunk["updated_at"] = _now().isoformat(timespec="seconds")
    _clear_wait_state(state)
    ws.save_transcribe_state(state)


def _switch_remaining_chunks_to_backend(
    ws: Workspace,
    plan: list[dict],
    state: dict,
    *,
    start_index: int,
    backend: str,
    error: Exception,
) -> None:
    for chunk in plan[start_index:]:
        chunk_state = _chunk_state(state, str(chunk["chunk_id"]))
        if chunk_state.get("status") == "pending":
            chunk["preferred_backend"] = backend
    state["job_mode"] = "remote_remaining"
    state["status"] = "running"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = str(error)
    ws.save_transcribe_plan(plan)
    ws.save_transcribe_state(state)


def _transcribe_from_subtitles(
    sub_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
    *,
    source: str = "subtitle",
) -> list[dict]:
    """Assign subtitle entries to segments, or create segments from entries."""
    entries = parse_subtitle_file(sub_path)
    if verbose:
        typer.echo(f"  Parsed {len(entries)} subtitle entries")

    if segments:
        # Assign entries to existing segments by time
        return _assign_entries_to_segments(entries, segments, source=source)
    else:
        # No segments — sentence-split the full transcript
        from yt2notion.segment import _split_by_duration

        max_seg = config.get("output", {}).get("max_segment_seconds", 900)
        split_segs = _split_by_duration(entries, max_seg)
        return [
            {
                "title": seg.title,
                "start_seconds": seg.start_seconds,
                "end_seconds": seg.end_seconds,
                "text": seg.text,
                "source": source,
            }
            for seg in split_segs
        ]


def transcribe_from_subtitles(
    sub_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    verbose: bool,
    *,
    source: str = "subtitle",
) -> list[dict]:
    """Public compatibility wrapper for subtitle transcript assignment."""
    return _transcribe_from_subtitles(
        sub_path,
        segments,
        metadata,
        config,
        verbose,
        source=source,
    )


def _assign_entries_to_segments(
    entries: list[SubtitleEntry], segments: list[dict], *, source: str = "subtitle"
) -> list[dict]:
    """Assign subtitle entries to segments by timestamp."""
    result: list[dict] = []
    for seg in segments:
        seg_entries = [
            e
            for e in entries
            if e.start_seconds >= seg["start_seconds"] and e.start_seconds < seg["end_seconds"]
        ]
        text = " ".join(e.text for e in seg_entries).strip()
        result.append(
            {
                "title": seg.get("title", ""),
                "start_seconds": seg["start_seconds"],
                "end_seconds": seg["end_seconds"],
                "text": text,
                "source": source,
            }
        )
    return result


def _build_segment_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    segments: list[dict],
    preferred_backend: str,
) -> list[dict]:
    existing = ws.load_transcribe_plan()
    if (
        isinstance(existing, list)
        and existing
        and len(existing) == len(segments)
        and all(
            isinstance(chunk, dict)
            and chunk.get("segment_index") == index
            and "audio_relpath" in chunk
            and "preferred_backend" in chunk
            for index, chunk in enumerate(existing)
        )
    ):
        return existing

    from yt2notion.audio import split_audio

    seg_dir = audio_path.parent / "segments"
    seg_files = split_audio(audio_path, segments, seg_dir)
    plan = [
        {
            "chunk_id": f"segment-{index + 1:03d}",
            "segment_index": index,
            "title": seg.get("title", f"Part {index + 1}"),
            "start_seconds": seg["start_seconds"],
            "end_seconds": seg["end_seconds"],
            "audio_relpath": _chunk_audio_ref(ws, seg_file),
            "preferred_backend": preferred_backend,
        }
        for index, (seg, seg_file) in enumerate(zip(segments, seg_files, strict=True))
    ]
    ws.save_transcribe_plan(plan)
    return plan


def _build_full_audio_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber: Transcriber,
    preferred_backend: str,
) -> list[dict]:
    existing = ws.load_transcribe_plan()
    if (
        isinstance(existing, list)
        and existing
        and all(
            isinstance(chunk, dict)
            and "segment_index" not in chunk
            and "audio_relpath" in chunk
            and "preferred_backend" in chunk
            for chunk in existing
        )
    ):
        return existing

    from yt2notion.audio import get_duration, split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    chunk_seconds = configured_chunk_seconds
    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    file_size = audio_path.stat().st_size
    oversize_full_audio = False

    if max_upload_bytes is not None and file_size > max_upload_bytes:
        oversize_full_audio = True
        chunk_seconds = _resolve_upload_budget_chunk_seconds(
            duration_seconds,
            file_size_bytes=file_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )

    if duration_seconds <= chunk_seconds:
        if oversize_full_audio:
            raise TranscriptionError(
                f"ASR full audio {audio_path.name} ({file_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )
        plan = [
            {
                "chunk_id": "chunk-001",
                "title": "Chunk 1",
                "start_seconds": 0.0,
                "end_seconds": duration_seconds,
                "audio_relpath": _chunk_audio_ref(ws, audio_path),
                "preferred_backend": preferred_backend,
            }
        ]
    else:
        chunk_specs = _build_full_audio_chunk_specs(duration_seconds, chunk_seconds)
        chunk_dir = audio_path.parent / "full_audio_chunks"
        chunk_files = split_audio(audio_path, chunk_specs, chunk_dir)
        plan = [
            {
                "chunk_id": f"chunk-{index + 1:03d}",
                "title": chunk_spec["title"],
                "start_seconds": chunk_spec["start_seconds"],
                "end_seconds": chunk_spec["end_seconds"],
                "audio_relpath": _chunk_audio_ref(ws, chunk_file),
                "preferred_backend": preferred_backend,
            }
            for index, (chunk_spec, chunk_file) in enumerate(
                zip(chunk_specs, chunk_files, strict=True)
            )
        ]

    ws.save_transcribe_plan(plan)
    return plan


def _load_required_chunk_payload(ws: Workspace, chunk_id: str) -> ChunkResultPayload:
    from yt2notion.transcribe.errors import TranscriptionError

    payload = ws.load_transcribe_chunk_result(chunk_id)
    if payload is None:
        raise TranscriptionError(f"Missing transcribe chunk result for {chunk_id}")
    return payload


def _segment_transcripts_from_plan(ws: Workspace, plan: list[dict]) -> list[dict]:
    result: list[dict] = []
    for chunk in plan:
        payload = _load_required_chunk_payload(ws, str(chunk["chunk_id"]))
        entries = _entries_from_chunk_payload(payload)
        result.append(
            {
                "title": chunk["title"],
                "start_seconds": chunk["start_seconds"],
                "end_seconds": chunk["end_seconds"],
                "text": " ".join(entry.text for entry in entries).strip(),
                "source": "asr",
            }
        )
    return result


def _merged_chunk_entries(ws: Workspace, plan: list[dict]) -> list[SubtitleEntry]:
    merged: list[SubtitleEntry] = []
    for chunk in plan:
        payload = _load_required_chunk_payload(ws, str(chunk["chunk_id"]))
        merged.extend(_entries_from_chunk_payload(payload))
    return merged


def _resolve_chunk_transcriber(
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


def _execute_chunk_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    plan: list[dict],
    state: dict,
    config: dict,
    primary_backend: str,
    transcriber: Transcriber,
    fallback_backend: str | None,
    fallback_transcriber_factory: TranscriberFactory | None,
    language: str | None,
    verbose: bool,
    progress_callback: ProgressCallback | None = None,
) -> None:
    from yt2notion.transcribe.errors import (
        TranscriptionDailyLimitError,
        TranscriptionHourlyLimitError,
    )

    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    for index, chunk in enumerate(plan):
        chunk_id = str(chunk["chunk_id"])
        chunk_state = _chunk_state(state, chunk_id)
        if chunk_state.get("status", "").startswith("completed_"):
            if ws.load_transcribe_chunk_result(chunk_id) is None:
                _mark_chunk_payload_missing(state, chunk_id)
                ws.save_transcribe_state(state)
            else:
                continue

        if state.get("status") == "waiting_ash" and state.get("next_attempt_at"):
            wait_target = str(state["next_attempt_at"])
            retry_after_seconds = max(
                0.0, (datetime.fromisoformat(wait_target) - _now()).total_seconds()
            )
            _emit_progress(
                progress_callback,
                "transcribe",
                "hourly_wait",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=str(chunk.get("preferred_backend", primary_backend)),
                    retry_after_seconds=round(retry_after_seconds, 3),
                    next_attempt_at=wait_target,
                    resumed_from_state=True,
                    ash_defer_count=int(state.get("ash_defer_count", 0)),
                ),
            )
            _wait_until_retryable_time(state.get("next_attempt_at"), verbose=verbose)
            _clear_wait_state(state)
            ws.save_transcribe_state(state)

        while True:
            backend = str(chunk.get("preferred_backend", primary_backend))
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_started",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    attempt=int(chunk_state.get("attempts", 0)) + 1,
                ),
            )
            active_transcriber = _resolve_chunk_transcriber(
                backend=backend,
                primary_backend=primary_backend,
                primary_transcriber=transcriber,
                fallback_backend=fallback_backend,
                fallback_transcriber_factory=fallback_transcriber_factory,
            )
            chunk_file = _resolve_chunk_audio_path(ws, str(chunk["audio_relpath"]))
            should_rebase = "segment_index" not in chunk
            try:
                entries = _transcribe_segment_entries_with_byte_budget(
                    audio_path=audio_path,
                    segment=chunk,
                    segment_file=chunk_file,
                    transcriber=active_transcriber,
                    language=language,
                    configured_chunk_seconds=configured_chunk_seconds,
                    verbose=verbose,
                    should_rebase=should_rebase,
                )
            except TranscriptionHourlyLimitError as exc:
                _mark_hourly_wait(state, chunk_id, exc)
                ws.save_transcribe_state(state)
                _emit_progress(
                    progress_callback,
                    "transcribe",
                    "hourly_wait",
                    _transcribe_progress_message(
                        chunk,
                        index=index,
                        total=len(plan),
                        backend=backend,
                        retry_after_seconds=round(float(exc.retry_after_seconds), 3),
                        next_attempt_at=state.get("next_attempt_at"),
                        resumed_from_state=False,
                        ash_defer_count=int(state.get("ash_defer_count", 0)),
                    ),
                )
                _wait_until_retryable_time(state.get("next_attempt_at"), verbose=verbose)
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
                    str(pending_chunk["chunk_id"])
                    for pending_chunk in plan[index:]
                    if _chunk_state(state, str(pending_chunk["chunk_id"])).get("status")
                    == "pending"
                ]
                _switch_remaining_chunks_to_backend(
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
                    _transcribe_progress_message(
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

            _mark_chunk_completed(ws, state, chunk_id, backend_used=backend, entries=entries)
            _emit_progress(
                progress_callback,
                "transcribe",
                "chunk_completed",
                _transcribe_progress_message(
                    chunk,
                    index=index,
                    total=len(plan),
                    backend=backend,
                    entries_count=len(entries),
                    attempts=int(_chunk_state(state, chunk_id).get("attempts", 0)),
                ),
            )
            break

    state["status"] = "completed"
    state["next_attempt_at"] = None
    state["defer_reason"] = None
    state["last_error"] = None
    ws.save_transcribe_state(state)


def _transcribe_from_audio(
    audio_path: Path,
    segments: list[dict],
    metadata: VideoMeta,
    config: dict,
    ws: Workspace,
    verbose: bool,
    *,
    transcriber: Transcriber,
    primary_backend: str = "remote",
    fallback_backend: str | None = None,
    fallback_transcriber_factory: TranscriberFactory | None = None,
    progress_callback: ProgressCallback | None = None,
) -> list[dict]:
    """Transcribe audio via ASR, optionally per-segment."""
    language = metadata.language or None

    if segments:
        plan = _build_segment_transcribe_plan(
            ws=ws,
            audio_path=audio_path,
            segments=segments,
            preferred_backend=primary_backend,
        )
        state = _load_or_create_transcribe_state(ws, plan, job_mode=primary_backend)
        _execute_chunk_plan(
            ws=ws,
            audio_path=audio_path,
            plan=plan,
            state=state,
            config=config,
            primary_backend=primary_backend,
            transcriber=transcriber,
            fallback_backend=fallback_backend,
            fallback_transcriber_factory=fallback_transcriber_factory,
            language=language,
            verbose=verbose,
            progress_callback=progress_callback,
        )
        return _segment_transcripts_from_plan(ws, plan)

    if verbose:
        typer.echo("  ASR on full audio (no pre-segmentation)...")
    plan = _build_full_audio_transcribe_plan(
        ws=ws,
        audio_path=audio_path,
        metadata=metadata,
        config=config,
        transcriber=transcriber,
        preferred_backend=primary_backend,
    )
    state = _load_or_create_transcribe_state(ws, plan, job_mode=primary_backend)
    _execute_chunk_plan(
        ws=ws,
        audio_path=audio_path,
        plan=plan,
        state=state,
        config=config,
        primary_backend=primary_backend,
        transcriber=transcriber,
        fallback_backend=fallback_backend,
        fallback_transcriber_factory=fallback_transcriber_factory,
        language=language,
        verbose=verbose,
        progress_callback=progress_callback,
    )
    entries = _merged_chunk_entries(ws, plan)
    if verbose:
        typer.echo(f"  {len(entries)} ASR segments returned")

    # Sentence-split into segments
    from yt2notion.segment import _split_by_duration

    max_seg = config.get("output", {}).get("max_segment_seconds", 900)
    split_segs = _split_by_duration(entries, max_seg)
    return [
        {
            "title": seg.title,
            "start_seconds": seg.start_seconds,
            "end_seconds": seg.end_seconds,
            "text": seg.text,
            "source": "asr",
        }
        for seg in split_segs
    ]


def _transcriber_max_upload_bytes(transcriber: Transcriber) -> int | None:
    raw_value = getattr(transcriber, "max_upload_bytes", None)
    if isinstance(raw_value, int) and raw_value > 0:
        return raw_value
    return None


def _resolve_upload_budget_chunk_seconds(
    duration_seconds: float,
    *,
    file_size_bytes: int,
    configured_chunk_seconds: int,
    max_upload_bytes: int,
) -> int:
    configured = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(configured_chunk_seconds))
    if duration_seconds <= 0 or file_size_bytes <= 0 or max_upload_bytes <= 0:
        return configured

    budget_seconds = duration_seconds * (max_upload_bytes / file_size_bytes) * 0.9
    budget_chunk = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(math.floor(budget_seconds)))
    return max(MIN_ASR_UPLOAD_CHUNK_SECONDS, min(configured, budget_chunk))


def _build_segment_subchunks(segment: dict, chunk_seconds: int) -> list[dict]:
    start = float(segment["start_seconds"])
    end = float(segment["end_seconds"])
    chunk = max(1.0, float(chunk_seconds))
    chunks: list[dict] = []
    index = 1
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk, end)
        chunks.append(
            {
                "title": f"{segment.get('title', 'Segment')} chunk {index}",
                "start_seconds": cursor,
                "end_seconds": chunk_end,
            }
        )
        cursor = chunk_end
        index += 1
    return chunks


def _transcribe_segment_entries_with_byte_budget(
    *,
    audio_path: Path,
    segment: dict,
    segment_file: Path,
    transcriber: Transcriber,
    language: str | None,
    configured_chunk_seconds: int,
    verbose: bool,
    should_rebase: bool = False,
) -> list[SubtitleEntry]:
    from yt2notion.audio import split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    segment_duration = float(segment["end_seconds"] - segment["start_seconds"])
    segment_size = segment_file.stat().st_size if segment_file.exists() else 0
    if max_upload_bytes is not None and segment_file.exists() and segment_size > max_upload_bytes:
        if segment_duration <= MIN_ASR_UPLOAD_CHUNK_SECONDS:
            raise TranscriptionError(
                f"ASR chunk {segment_file.name} ({segment_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )

        chunk_seconds = _resolve_upload_budget_chunk_seconds(
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
        subchunks = _build_segment_subchunks(segment, chunk_seconds)
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
                _transcribe_segment_entries_with_byte_budget(
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

    entries = transcriber.transcribe(segment_file, language=language)
    if should_rebase:
        return _rebase_chunk_entries(entries, segment)
    return entries


def _transcribe_full_audio_entries(
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber: Transcriber,
    *,
    language: str | None,
    verbose: bool,
) -> list[SubtitleEntry]:
    """Transcribe full audio, chunking long files to keep remote ASR requests bounded."""
    from yt2notion.audio import get_duration, split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    configured_chunk_seconds = _resolve_full_audio_asr_chunk_seconds(config)
    chunk_seconds = configured_chunk_seconds
    max_upload_bytes = _transcriber_max_upload_bytes(transcriber)
    file_size = audio_path.stat().st_size
    oversize_full_audio = False

    if max_upload_bytes is not None:
        if file_size <= max_upload_bytes:
            return transcriber.transcribe(audio_path, language=language)
        oversize_full_audio = True
        chunk_seconds = _resolve_upload_budget_chunk_seconds(
            duration_seconds,
            file_size_bytes=file_size,
            configured_chunk_seconds=configured_chunk_seconds,
            max_upload_bytes=max_upload_bytes,
        )

    if duration_seconds <= chunk_seconds:
        if oversize_full_audio:
            raise TranscriptionError(
                f"ASR full audio {audio_path.name} ({file_size} bytes) exceeds "
                f"max_upload_bytes ({max_upload_bytes}) at minimum chunk size "
                f"({MIN_ASR_UPLOAD_CHUNK_SECONDS}s)"
            )
        return transcriber.transcribe(audio_path, language=language)

    chunk_specs = _build_full_audio_chunk_specs(duration_seconds, chunk_seconds)
    chunk_dir = audio_path.parent / "full_audio_chunks"
    chunk_files = split_audio(audio_path, chunk_specs, chunk_dir)

    all_entries: list[SubtitleEntry] = []
    for index, (chunk_spec, chunk_file) in enumerate(zip(chunk_specs, chunk_files, strict=True)):
        if verbose:
            start_label = seconds_to_display(chunk_spec["start_seconds"])
            end_label = seconds_to_display(chunk_spec["end_seconds"])
            typer.echo(f"  ASR chunk [{index + 1}/{len(chunk_specs)}] {start_label}-{end_label}")

        chunk_entries = _transcribe_segment_entries_with_byte_budget(
            audio_path=audio_path,
            segment=chunk_spec,
            segment_file=chunk_file,
            transcriber=transcriber,
            language=language,
            configured_chunk_seconds=chunk_seconds,
            verbose=verbose,
            should_rebase=True,
        )
        all_entries.extend(chunk_entries)

    return all_entries


def _resolve_full_audio_asr_chunk_seconds(config: dict) -> int:
    """Choose a safe chunk size for long full-audio ASR uploads."""
    asr_cfg = config.get("extract", {}).get("asr", {})
    configured = asr_cfg.get("chunk_seconds")
    if isinstance(configured, int) and configured > 0:
        return configured

    max_segment = config.get("output", {}).get("max_segment_seconds", FULL_AUDIO_ASR_CHUNK_SECONDS)
    return max(1, min(int(max_segment), FULL_AUDIO_ASR_CHUNK_SECONDS))


def _build_full_audio_chunk_specs(duration_seconds: float, chunk_seconds: int) -> list[dict]:
    """Create synthetic contiguous segments for chunked full-audio ASR."""
    chunks: list[dict] = []
    start = 0.0
    index = 1
    while start < duration_seconds:
        end = min(start + chunk_seconds, duration_seconds)
        chunks.append(
            {
                "title": f"Chunk {index}",
                "start_seconds": start,
                "end_seconds": end,
            }
        )
        start = end
        index += 1
    return chunks


def _rebase_chunk_entries(entries: list[SubtitleEntry], chunk_spec: dict) -> list[SubtitleEntry]:
    """Map chunk-local ASR timestamps back to the original timeline and drop overlap duplicates."""
    chunk_start = float(chunk_spec["start_seconds"])
    chunk_end = float(chunk_spec["end_seconds"])
    clip_start = max(0.0, chunk_start - ASR_CHUNK_PADDING_SECONDS)

    rebased: list[SubtitleEntry] = []
    for entry in entries:
        adjusted_start = clip_start + entry.start_seconds
        adjusted_end = clip_start + entry.end_seconds
        midpoint = (adjusted_start + adjusted_end) / 2
        if midpoint < chunk_start or midpoint >= chunk_end:
            continue

        rebased.append(
            SubtitleEntry(
                start_seconds=max(chunk_start, adjusted_start),
                end_seconds=min(chunk_end, adjusted_end),
                text=entry.text,
            )
        )

    return rebased


def rebase_chunk_entries(entries: list[SubtitleEntry], chunk_spec: dict) -> list[SubtitleEntry]:
    """Public compatibility wrapper for timestamp rebasing tests/callers."""
    return _rebase_chunk_entries(entries, chunk_spec)


def transcribe_full_audio_entries(
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber: Transcriber,
    *,
    language: str | None,
    verbose: bool,
) -> list[SubtitleEntry]:
    """Public compatibility wrapper for full-audio transcription helpers."""
    return _transcribe_full_audio_entries(
        audio_path,
        metadata,
        config,
        transcriber,
        language=language,
        verbose=verbose,
    )


def describe_backend_outcome(ws: Workspace, *, default_backend: str) -> str:
    """Describe actual backend use from transcribe checkpoint state."""
    state = ws.load_transcribe_state()
    if not isinstance(state, dict):
        return default_backend

    backends = [
        str(chunk.get("backend_used"))
        for chunk in state.get("chunks", [])
        if isinstance(chunk, dict) and chunk.get("backend_used")
    ]
    if not backends:
        return default_backend

    unique = list(dict.fromkeys(backends))
    if len(unique) == 1:
        return unique[0]
    return "mixed: " + ", ".join(unique)
