"""Build immutable cue-level subtitle sources from transcription artifacts."""

from __future__ import annotations

from typing import TYPE_CHECKING

from yt2notion.process import parse_subtitle_file
from yt2notion.subtitle_pack.models import SourceCue

if TYPE_CHECKING:
    from yt2notion.transcript_artifacts import MediaTranscribeResult


def build_source_cues(transcription: MediaTranscribeResult) -> tuple[str, list[SourceCue]]:
    """Restore timed source cues from subtitles, ASR chunks, or transcript segments."""
    subtitle_path = transcription.workspace.subtitle_path
    source_kind = transcription.workspace.load_subtitle_source()
    if subtitle_path is not None:
        entries = parse_subtitle_file(subtitle_path)
        cues = [
            SourceCue(
                id=f"cue-{index:06d}",
                start_ms=round(entry.start_seconds * 1000),
                end_ms=round(entry.end_seconds * 1000),
                original_text=entry.text,
            )
            for index, entry in enumerate(entries, start=1)
        ]
        return source_kind or "subtitle", cues

    chunk_cues = _asr_cues_from_chunks(transcription)
    if chunk_cues:
        return "asr", chunk_cues

    transcripts = transcription.workspace.load_transcripts() or []
    cues = [
        SourceCue(
            id=f"cue-{index:06d}",
            start_ms=round(float(segment.start_seconds) * 1000),
            end_ms=round(float(segment.end_seconds) * 1000),
            original_text=segment.text.strip(),
        )
        for index, segment in enumerate(transcripts, start=1)
        if segment.text.strip()
    ]
    sources = {item.source for item in transcripts}
    return ("asr" if "asr" in sources else "transcript"), cues


def _asr_cues_from_chunks(transcription: MediaTranscribeResult) -> list[SourceCue]:
    plan = transcription.workspace.load_transcribe_plan()
    if not isinstance(plan, list) or not plan:
        return []
    entries: list[tuple[float, float, str]] = []
    for chunk in plan:
        if not isinstance(chunk, dict) or "chunk_id" not in chunk:
            return []
        payload = transcription.workspace.load_transcribe_chunk_result(str(chunk["chunk_id"]))
        if not isinstance(payload, list):
            return []
        chunk_start = float(chunk.get("start_seconds", 0))
        chunk_duration = float(chunk.get("end_seconds", 0)) - chunk_start
        payload_end = max(
            (float(item.get("end_seconds", 0)) for item in payload if isinstance(item, dict)),
            default=0,
        )
        offset = (
            chunk_start if "segment_index" in chunk and payload_end <= chunk_duration + 0.001 else 0
        )
        for item in payload:
            if not isinstance(item, dict):
                return []
            text = str(item.get("text", "")).strip()
            if text:
                entries.append(
                    (
                        float(item.get("start_seconds", 0)) + offset,
                        float(item.get("end_seconds", 0)) + offset,
                        text,
                    )
                )
    entries.sort(key=lambda item: (item[0], item[1]))
    return [
        SourceCue(
            id=f"cue-{index:06d}",
            start_ms=round(start * 1000),
            end_ms=round(end * 1000),
            original_text=text,
        )
        for index, (start, end, text) in enumerate(entries, start=1)
    ]
