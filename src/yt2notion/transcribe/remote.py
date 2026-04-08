"""Remote ASR transcription backend via HTTP endpoint."""

from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

import httpx

from yt2notion.process import SubtitleEntry
from yt2notion.retry import RetryExhaustedError, retry
from yt2notion.transcribe.errors import TranscriptionError


class RemoteTranscriber:
    """Transcriber that calls a remote FastAPI ASR endpoint."""

    max_upload_bytes: int | None = None

    def __init__(
        self,
        endpoint: str,
        timeout: float = 1800.0,
        *,
        healthcheck_path: str = "/health",
        healthcheck_timeout: float = 3.0,
        restart_before_transcribe: bool = False,
        restart_on_unhealthy: bool = False,
        restart_command: str = "",
        restart_readiness_timeout: float = 90.0,
        restart_readiness_interval: float = 3.0,
        restart_grace_seconds: float = 5.0,
    ) -> None:
        self.endpoint = endpoint.rstrip("/")
        self.timeout = timeout
        self.healthcheck_path = f"/{healthcheck_path.lstrip('/')}" if healthcheck_path else ""
        self.healthcheck_timeout = max(0.1, float(healthcheck_timeout))
        self.restart_before_transcribe = restart_before_transcribe
        self.restart_on_unhealthy = restart_on_unhealthy
        self.restart_command = restart_command.strip()
        self.restart_readiness_timeout = max(0.1, float(restart_readiness_timeout))
        self.restart_readiness_interval = max(0.1, float(restart_readiness_interval))
        self.restart_grace_seconds = max(0.0, float(restart_grace_seconds))
        self._startup_checked = False

    def transcribe(self, audio_path: Path, *, language: str | None = None) -> list[SubtitleEntry]:
        """Send audio to remote ASR service, return SubtitleEntry list."""
        self._ensure_service_ready_once()

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
        except RetryExhaustedError as e:
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

    def _ensure_service_ready_once(self) -> None:
        if self._startup_checked:
            return

        if self.restart_before_transcribe:
            self._restart_asr_service("restart_before_transcribe=true")
            self._wait_until_ready_after_restart()
            self._startup_checked = True
            return

        if self.restart_on_unhealthy:
            health = self._check_health()
            if health is False:
                self._restart_asr_service("health check failed before transcription")
                self._wait_until_ready_after_restart()

        self._startup_checked = True

    def _check_health(self) -> bool | None:
        """Return True/False for healthy/unhealthy, None if health endpoint is unsupported."""
        if not self.healthcheck_path:
            return None

        health_url = f"{self.endpoint}{self.healthcheck_path}"
        try:
            response = httpx.get(health_url, timeout=self.healthcheck_timeout)
        except httpx.HTTPError:
            return False

        if response.status_code == 404:
            return None
        return 200 <= response.status_code < 300

    def _restart_asr_service(self, reason: str) -> None:
        if not self.restart_command:
            raise TranscriptionError(
                "ASR restart is enabled but extract.asr.restart_command is empty"
            )

        try:
            subprocess.run(
                self.restart_command,
                shell=True,
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            detail = (e.stderr or e.stdout or str(e)).strip()
            raise TranscriptionError(f"ASR restart command failed ({reason}): {detail}") from e

    def _wait_until_ready_after_restart(self) -> None:
        deadline = time.monotonic() + self.restart_readiness_timeout
        while time.monotonic() < deadline:
            health = self._check_health()
            if health is True:
                return
            if health is None:
                if self.restart_grace_seconds > 0:
                    time.sleep(self.restart_grace_seconds)
                return
            time.sleep(self.restart_readiness_interval)

        raise TranscriptionError(
            "ASR service did not become healthy after restart within "
            f"{self.restart_readiness_timeout:.1f}s"
        )
