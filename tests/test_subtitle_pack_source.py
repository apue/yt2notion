"""Offline source-adapter contracts for subtitle cues."""

from __future__ import annotations

from pathlib import Path

from tests.subtitle_pack_support import make_transcription
from yt2notion.subtitle_pack.source import build_source_cues
from yt2notion.transcribe.contracts import ChunkTranscriptEntry, TranscribeChunk


def test_asr_chunk_relative_timing_is_restored_to_absolute_video_time(tmp_path: Path) -> None:
    transcription = make_transcription(tmp_path, source_kind="automatic_caption")
    transcription.workspace.subtitle_path.unlink()
    (transcription.workspace.dir / "subtitle_source.json").unlink()
    transcription.workspace.save_transcribe_plan(
        [
            TranscribeChunk(
                chunk_id="segment-001",
                segment_index=0,
                title="Lecture",
                start_seconds=60,
                end_seconds=90,
                audio_relpath="segments/001.mp3",
                preferred_backend="groq",
            )
        ]
    )
    transcription.workspace.save_transcribe_chunk_result(
        "segment-001",
        [
            ChunkTranscriptEntry(
                start_seconds=1.0,
                end_seconds=4.5,
                text="Thank you Graeme.",
            )
        ],
    )

    source_kind, cues = build_source_cues(transcription)

    assert source_kind == "asr"
    assert [(cue.start_ms, cue.end_ms, cue.original_text) for cue in cues] == [
        (61_000, 64_500, "Thank you Graeme.")
    ]
