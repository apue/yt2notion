"""Tests for the Transcriber Protocol and layered transcribe errors."""

from __future__ import annotations

from pathlib import Path

from yt2notion.process import SubtitleEntry
from yt2notion.transcribe.base import Transcriber
from yt2notion.transcribe.errors import (
    TranscriptionError,
    TranscriptionQuotaError,
    TranscriptionServerError,
)
from yt2notion.transcribe.remote import RemoteTranscriber
from yt2notion.transcribe.remote import TranscriptionError as RemoteTranscriptionError


def test_quota_error_subclass() -> None:
    assert issubclass(TranscriptionQuotaError, TranscriptionError)


def test_server_error_subclass() -> None:
    assert issubclass(TranscriptionServerError, TranscriptionError)


def test_remote_reexports_same_error_class() -> None:
    assert RemoteTranscriptionError is TranscriptionError


def test_protocol_and_error_import_paths() -> None:
    assert Transcriber.__module__ == "yt2notion.transcribe.base"
    assert TranscriptionError.__module__ == "yt2notion.transcribe.errors"


def test_remote_transcriber_max_upload_bytes_default_none() -> None:
    transcriber = RemoteTranscriber(endpoint="http://example.invalid")
    assert transcriber.max_upload_bytes is None


def test_protocol_structural_conformance() -> None:
    class FakeTranscriber:
        max_upload_bytes: int | None = 1024

        def transcribe(
            self, audio_path: Path, *, language: str | None = None
        ) -> list[SubtitleEntry]:
            return [SubtitleEntry(start_seconds=0.0, end_seconds=1.0, text="hi")]

    instance: Transcriber = FakeTranscriber()
    result = instance.transcribe(Path("/tmp/x.mp3"), language="en")
    assert len(result) == 1
    assert result[0].text == "hi"
    assert instance.max_upload_bytes == 1024
