"""Audio transcription plan and chunk construction."""

from __future__ import annotations

import math
from collections.abc import Sequence
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.domain import SegmentSpec
from yt2notion.process import SubtitleEntry
from yt2notion.transcribe.contracts import TranscribeChunk

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.transcribe.base import Transcriber
    from yt2notion.workspace import Workspace

FULL_AUDIO_ASR_CHUNK_SECONDS = 300
MIN_ASR_UPLOAD_CHUNK_SECONDS = 30
ASR_CHUNK_PADDING_SECONDS = 0.5


def build_segment_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    segments: Sequence[SegmentSpec],
    preferred_backend: str,
) -> list[TranscribeChunk]:
    """Build or reuse the durable plan for pre-segmented audio."""
    existing = ws.load_transcribe_plan()
    if (
        existing
        and len(existing) == len(segments)
        and all(
            chunk.segment_index == index and bool(chunk.audio_relpath)
            for index, chunk in enumerate(existing)
        )
    ):
        return existing

    from yt2notion.audio import split_audio

    seg_dir = audio_path.parent / "segments"
    seg_files = split_audio(audio_path, segments, seg_dir)
    plan = [
        TranscribeChunk(
            chunk_id=f"segment-{index + 1:03d}",
            title=seg.title or f"Part {index + 1}",
            start_seconds=seg.start_seconds,
            end_seconds=seg.end_seconds,
            audio_relpath=chunk_audio_ref(ws, seg_file),
            preferred_backend=preferred_backend,
            segment_index=index,
        )
        for index, (seg, seg_file) in enumerate(zip(segments, seg_files, strict=True))
    ]
    ws.save_transcribe_plan(plan)
    return plan


def build_full_audio_transcribe_plan(
    *,
    ws: Workspace,
    audio_path: Path,
    metadata: VideoMeta,
    config: dict,
    transcriber: Transcriber,
    preferred_backend: str,
) -> list[TranscribeChunk]:
    """Build or reuse a durable plan for unsegmented audio."""
    existing = ws.load_transcribe_plan()
    if existing and all(
        chunk.segment_index is None and bool(chunk.audio_relpath) for chunk in existing
    ):
        return existing

    from yt2notion.audio import get_duration, split_audio
    from yt2notion.transcribe.errors import TranscriptionError

    duration_seconds = float(metadata.duration_seconds or get_duration(audio_path))
    configured_chunk_seconds = resolve_full_audio_asr_chunk_seconds(config)
    chunk_seconds = configured_chunk_seconds
    max_upload_bytes = transcriber_max_upload_bytes(transcriber)
    file_size = audio_path.stat().st_size
    oversize_full_audio = False

    if max_upload_bytes is not None and file_size > max_upload_bytes:
        oversize_full_audio = True
        chunk_seconds = resolve_upload_budget_chunk_seconds(
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
            TranscribeChunk(
                chunk_id="chunk-001",
                title="Chunk 1",
                start_seconds=0.0,
                end_seconds=duration_seconds,
                audio_relpath=chunk_audio_ref(ws, audio_path),
                preferred_backend=preferred_backend,
            )
        ]
    else:
        chunk_specs = build_full_audio_chunk_specs(duration_seconds, chunk_seconds)
        chunk_dir = audio_path.parent / "full_audio_chunks"
        chunk_files = split_audio(audio_path, chunk_specs, chunk_dir)
        plan = [
            TranscribeChunk(
                chunk_id=f"chunk-{index + 1:03d}",
                title=chunk_spec.title,
                start_seconds=chunk_spec.start_seconds,
                end_seconds=chunk_spec.end_seconds,
                audio_relpath=chunk_audio_ref(ws, chunk_file),
                preferred_backend=preferred_backend,
            )
            for index, (chunk_spec, chunk_file) in enumerate(
                zip(chunk_specs, chunk_files, strict=True)
            )
        ]

    ws.save_transcribe_plan(plan)
    return plan


def chunk_audio_ref(ws: Workspace, path: Path) -> str:
    """Return a stable workspace-relative path when possible."""
    try:
        return str(path.relative_to(ws.dir))
    except ValueError:
        return str(path)


def resolve_chunk_audio_path(ws: Workspace, audio_ref: str) -> Path:
    """Resolve a planned audio reference against its workspace."""
    path = Path(audio_ref)
    if path.is_absolute():
        return path
    return ws.dir / path


def transcriber_max_upload_bytes(transcriber: Transcriber) -> int | None:
    """Read a valid positive upload limit from a transcriber."""
    raw_value = getattr(transcriber, "max_upload_bytes", None)
    if isinstance(raw_value, int) and raw_value > 0:
        return raw_value
    return None


def resolve_upload_budget_chunk_seconds(
    duration_seconds: float,
    *,
    file_size_bytes: int,
    configured_chunk_seconds: int,
    max_upload_bytes: int,
) -> int:
    """Estimate a conservative chunk duration under an upload byte budget."""
    configured = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(configured_chunk_seconds))
    if duration_seconds <= 0 or file_size_bytes <= 0 or max_upload_bytes <= 0:
        return configured

    budget_seconds = duration_seconds * (max_upload_bytes / file_size_bytes) * 0.9
    budget_chunk = max(MIN_ASR_UPLOAD_CHUNK_SECONDS, int(math.floor(budget_seconds)))
    return max(MIN_ASR_UPLOAD_CHUNK_SECONDS, min(configured, budget_chunk))


def build_segment_subchunks(
    segment: SegmentSpec | TranscribeChunk,
    chunk_seconds: int,
) -> list[SegmentSpec]:
    """Build contiguous child chunks over one planned segment."""
    start = segment.start_seconds
    end = segment.end_seconds
    chunk = max(1.0, float(chunk_seconds))
    chunks: list[SegmentSpec] = []
    index = 1
    cursor = start
    while cursor < end:
        chunk_end = min(cursor + chunk, end)
        chunks.append(
            SegmentSpec(
                title=f"{segment.title or 'Segment'} chunk {index}",
                start_seconds=cursor,
                end_seconds=chunk_end,
            )
        )
        cursor = chunk_end
        index += 1
    return chunks


def resolve_full_audio_asr_chunk_seconds(config: dict) -> int:
    """Choose a safe chunk size for long full-audio ASR uploads."""
    asr_cfg = config.get("extract", {}).get("asr", {})
    configured = asr_cfg.get("chunk_seconds")
    if isinstance(configured, int) and configured > 0:
        return configured

    max_segment = config.get("output", {}).get("max_segment_seconds", FULL_AUDIO_ASR_CHUNK_SECONDS)
    return max(1, min(int(max_segment), FULL_AUDIO_ASR_CHUNK_SECONDS))


def build_full_audio_chunk_specs(
    duration_seconds: float,
    chunk_seconds: int,
) -> list[SegmentSpec]:
    """Create synthetic contiguous segments for chunked full-audio ASR."""
    chunks: list[SegmentSpec] = []
    start = 0.0
    index = 1
    while start < duration_seconds:
        end = min(start + chunk_seconds, duration_seconds)
        chunks.append(
            SegmentSpec(
                title=f"Chunk {index}",
                start_seconds=start,
                end_seconds=end,
            )
        )
        start = end
        index += 1
    return chunks


def rebase_chunk_entries(
    entries: list[SubtitleEntry],
    chunk_spec: SegmentSpec | TranscribeChunk,
) -> list[SubtitleEntry]:
    """Map chunk-local timestamps to the original timeline and drop overlap duplicates."""
    chunk_start = chunk_spec.start_seconds
    chunk_end = chunk_spec.end_seconds
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
