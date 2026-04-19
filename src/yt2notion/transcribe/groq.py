"""Groq audio transcription backend (OpenAI-compatible)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx

from yt2notion.process import SubtitleEntry
from yt2notion.retry import RetryExhaustedError, retry
from yt2notion.transcribe.errors import (
    TranscriptionDailyLimitError,
    TranscriptionError,
    TranscriptionHourlyLimitError,
    TranscriptionServerError,
)

DEFAULT_HOURLY_RETRY_AFTER_SECONDS = 3600

_SUFFIX_TO_MIME: dict[str, str] = {
    ".mp3": "audio/mpeg",
    ".m4a": "audio/mp4",
    ".mp4": "audio/mp4",
    ".wav": "audio/wav",
    ".ogg": "audio/ogg",
    ".webm": "audio/webm",
}


def _mime_type_for_audio(path: Path) -> str | None:
    return _SUFFIX_TO_MIME.get(path.suffix.lower())


def _parse_retry_after_seconds(response: httpx.Response) -> float:
    raw = response.headers.get("retry-after", "").strip()
    if not raw:
        return float(DEFAULT_HOURLY_RETRY_AFTER_SECONDS)
    try:
        parsed = float(raw)
    except ValueError:
        return float(DEFAULT_HOURLY_RETRY_AFTER_SECONDS)
    return parsed if parsed > 0 else float(DEFAULT_HOURLY_RETRY_AFTER_SECONDS)


def _quota_error_text(response: httpx.Response) -> str:
    parts: list[str] = []
    try:
        payload: Any = response.json()
    except json.JSONDecodeError:
        payload = None

    if isinstance(payload, dict):
        error_payload = payload.get("error")
        if isinstance(error_payload, dict):
            message = error_payload.get("message")
            code = error_payload.get("code")
            if isinstance(message, str):
                parts.append(message)
            if isinstance(code, str):
                parts.append(code)
        elif isinstance(error_payload, str):
            parts.append(error_payload)

    if response.text:
        parts.append(response.text)
    return " ".join(parts).lower()


def _looks_like_daily_quota_error(response: httpx.Response) -> bool:
    text = _quota_error_text(response)
    daily_markers = (
        "daily quota",
        "daily limit",
        "daily rate limit",
        "quota exceeded for today",
        "quota for today",
        "today's quota",
        "per day",
        "day limit",
        "24-hour quota",
        "24 hour quota",
    )
    return any(marker in text for marker in daily_markers)


class GroqTranscriber:
    """Transcriber that calls Groq's OpenAI-compatible audio transcription endpoint."""

    max_upload_bytes: int

    def __init__(
        self,
        api_key: str,
        *,
        model: str = "whisper-large-v3-turbo",
        endpoint: str = "https://api.groq.com/openai/v1/audio/transcriptions",
        max_upload_bytes: int = 24_000_000,
        timeout_seconds: float = 600.0,
    ) -> None:
        self.api_key = api_key
        self.model = model
        self.endpoint = endpoint
        self.max_upload_bytes = max_upload_bytes
        self.timeout_seconds = timeout_seconds

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> list[SubtitleEntry]:
        size = audio_path.stat().st_size
        if size > self.max_upload_bytes:
            raise TranscriptionError(
                f"audio file {audio_path.name} ({size} bytes) exceeds "
                f"max_upload_bytes ({self.max_upload_bytes})"
            )

        data: dict[str, str] = {
            "model": self.model,
            "response_format": "verbose_json",
        }
        if language:
            data["language"] = language

        headers = {"Authorization": f"Bearer {self.api_key}"}

        class _RetryableServerError(Exception):
            """5xx server error eligible for retry."""

        last_server_error: list[Exception] = []

        def _post() -> httpx.Response:
            with open(audio_path, "rb") as f:
                mime_type = _mime_type_for_audio(audio_path)
                if mime_type is None:
                    files = {"file": (audio_path.name, f)}
                else:
                    files = {"file": (audio_path.name, f, mime_type)}
                response = httpx.post(
                    self.endpoint,
                    files=files,
                    data=data,
                    headers=headers,
                    timeout=self.timeout_seconds,
                )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as e:
                code = e.response.status_code
                if code == 429:
                    retry_after = _parse_retry_after_seconds(e.response)
                    if _looks_like_daily_quota_error(e.response):
                        raise TranscriptionDailyLimitError(
                            f"Groq daily quota exceeded: {e}",
                            retry_after_seconds=retry_after,
                        ) from e
                    raise TranscriptionHourlyLimitError(
                        f"Groq hourly rate limit exceeded: {e}",
                        retry_after_seconds=retry_after,
                    ) from e
                if code >= 500:
                    err = _RetryableServerError(f"Groq server error {code}: {e}")
                    last_server_error.append(err)
                    raise err from e
                raise TranscriptionError(f"Groq request failed: {e}") from e
            except httpx.HTTPError as e:
                raise TranscriptionError(f"Groq request failed: {e}") from e
            return response

        try:
            response = retry(
                _post,
                max_retries=3,
                base_delay=5.0,
                retryable=(
                    httpx.ConnectError,
                    httpx.TimeoutException,
                    _RetryableServerError,
                ),
                label=f"Groq transcribe {audio_path.name}",
            )
        except RetryExhaustedError as e:
            if last_server_error:
                raise TranscriptionServerError(str(last_server_error[-1])) from e
            raise TranscriptionError(str(e)) from e

        try:
            result = response.json()
        except json.JSONDecodeError as e:
            raise TranscriptionError(f"Groq response was not valid JSON: {e}") from e

        segments = result.get("segments") or []

        return [
            SubtitleEntry(
                start_seconds=seg["start"],
                end_seconds=seg["end"],
                text=seg["text"].strip(),
            )
            for seg in segments
            if seg.get("text", "").strip()
        ]
