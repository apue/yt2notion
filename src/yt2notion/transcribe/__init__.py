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
        return RemoteTranscriber(endpoint=endpoint)

    raise ValueError(f"Unknown ASR backend: {backend!r}. Supported: remote")
