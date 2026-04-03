"""Remote ASR transcription backend via HTTP endpoint."""

from __future__ import annotations

import json
from pathlib import Path

import httpx

from yt2notion.process import SubtitleEntry
from yt2notion.retry import RetryExhausted, retry


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

        class _RetryableStatusError(Exception):
            """Raised for HTTP 5xx responses that should be retried."""

        def _post() -> httpx.Response:
            with open(audio_path, "rb") as f:
                files = {"file": (audio_path.name, f, "audio/mpeg")}
                response = httpx.post(
                    url,
                    files=files,
                    data=data,
                    timeout=self.timeout,
                )
                try:
                    response.raise_for_status()
                except httpx.HTTPStatusError as e:
                    if e.response.status_code >= 500:
                        raise _RetryableStatusError(f"ASR server error: {e}") from e
                    raise TranscriptionError(f"ASR request failed: {e}") from e
                except httpx.HTTPError as e:
                    raise TranscriptionError(f"ASR request failed: {e}") from e
                return response

        try:
            response = retry(
                _post,
                max_retries=3,
                base_delay=10.0,
                retryable=(
                    httpx.ConnectError,
                    httpx.TimeoutException,
                    _RetryableStatusError,
                ),
                label=f"ASR transcribe {audio_path.name}",
            )
        except RetryExhausted as e:
            raise TranscriptionError(f"ASR request failed: {e}") from e

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise TranscriptionError(f"ASR response was not valid JSON: {e}") from e

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
