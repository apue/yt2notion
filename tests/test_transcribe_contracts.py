"""Strict JSON-ingress contracts for resumable transcription artifacts."""

from __future__ import annotations

import pytest

from yt2notion.transcribe.contracts import (
    decode_chunk_entries,
    decode_transcribe_plan,
    decode_transcribe_state,
)


def test_plan_codec_rejects_reversed_timeline() -> None:
    with pytest.raises(ValueError, match="ends before"):
        decode_transcribe_plan(
            [
                {
                    "chunk_id": "chunk-001",
                    "title": "Part 1",
                    "start_seconds": 12,
                    "end_seconds": 7,
                    "audio_relpath": "chunks/001.mp3",
                    "preferred_backend": "groq",
                }
            ]
        )


def test_state_codec_rejects_non_object_chunk() -> None:
    with pytest.raises(ValueError, match="list of objects"):
        decode_transcribe_state(
            {
                "version": 1,
                "job_mode": "groq",
                "status": "running",
                "next_attempt_at": None,
                "last_error": None,
                "defer_reason": None,
                "ash_defer_count": 0,
                "chunks": ["chunk-001"],
            }
        )


def test_chunk_codec_rejects_boolean_timestamp() -> None:
    with pytest.raises(ValueError, match="must be a number"):
        decode_chunk_entries(
            [
                {
                    "start_seconds": True,
                    "end_seconds": 2,
                    "text": "hello",
                    "source": "asr",
                }
            ]
        )
