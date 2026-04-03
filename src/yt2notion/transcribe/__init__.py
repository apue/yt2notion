"""Transcriber backend factory."""

from __future__ import annotations

import os
from typing import Any


def create_transcriber(config: dict) -> Any:
    """Create a Transcriber instance based on config.

    Supports env var fallback: ASR_ENDPOINT.
    """
    extract_cfg = config.get("extract", {})
    asr_cfg = extract_cfg.get("asr", {})
    backend = asr_cfg.get("backend", "remote")

    if backend == "remote":
        from yt2notion.transcribe.remote import RemoteTranscriber

        endpoint = asr_cfg.get("endpoint", "") or os.environ.get("ASR_ENDPOINT", "")
        if not endpoint:
            raise ValueError(
                "ASR endpoint required. "
                "Set extract.asr.endpoint in config.yaml or ASR_ENDPOINT env var."
            )
        return RemoteTranscriber(
            endpoint=endpoint,
            healthcheck_path=asr_cfg.get("healthcheck_path", "/health"),
            healthcheck_timeout=asr_cfg.get("healthcheck_timeout_seconds", 3.0),
            restart_before_transcribe=asr_cfg.get("restart_before_transcribe", False),
            restart_on_unhealthy=asr_cfg.get("restart_on_unhealthy", False),
            restart_command=asr_cfg.get("restart_command", ""),
            restart_readiness_timeout=asr_cfg.get("restart_readiness_timeout_seconds", 90.0),
            restart_readiness_interval=asr_cfg.get("restart_readiness_interval_seconds", 3.0),
            restart_grace_seconds=asr_cfg.get("restart_grace_seconds", 5.0),
        )

    raise ValueError(f"Unknown ASR backend: {backend!r}. Supported: remote")
