"""Remote ASR transcription backend via HTTP endpoint."""

from __future__ import annotations

from pathlib import Path

import httpx

from yt2notion.process import SubtitleEntry


class TranscriptionError(Exception):
    """Raised when ASR transcription fails."""


class RemoteTranscriber:
    """Transcriber that calls a remote FastAPI ASR endpoint."""

    def __init__(self, endpoint: str, timeout: float = 1800.0) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> list[SubtitleEntry]:
        """Send audio to remote ASR service, return SubtitleEntry list."""
        url = f"{self.endpoint}/transcribe"
        data: dict[str, str] = {}
        if language:
            data["language"] = language

        with open(audio_path, "rb") as f:
            files = {"file": (audio_path.name, f, "audio/mpeg")}
            try:
                response = httpx.post(
                    url,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
                response.raise_for_status()
            except httpx.HTTPError as e:
                raise TranscriptionError(f"ASR request failed: {e}") from e

        result = response.json()
        segments = result.get("segments", [])

        return [
            SubtitleEntry(
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                text=seg["text"].strip(),
            )
            for seg in segments
            if seg.get("text", "").strip()
        ]
