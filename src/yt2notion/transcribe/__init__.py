"""Transcriber backend factory."""

from __future__ import annotations

import os
from typing import Any


def _resolve_asr_config(config: dict) -> dict:
    extract_cfg = config.get("extract", {})
    return extract_cfg.get("asr", {})


def _create_remote_transcriber(asr_cfg: dict) -> Any:
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


def _create_groq_transcriber(asr_cfg: dict) -> Any:
    from yt2notion.transcribe.groq import GroqTranscriber

    groq_cfg = asr_cfg.get("groq", {})
    api_key = groq_cfg.get("api_key", "") or os.environ.get("GROQ_API_KEY", "")
    if not api_key:
        raise ValueError(
            "GROQ API key required. Set extract.asr.groq.api_key or GROQ_API_KEY env var."
        )
    return GroqTranscriber(
        api_key=api_key,
        model=groq_cfg.get("model", "whisper-large-v3-turbo"),
        endpoint=groq_cfg.get("endpoint", "https://api.groq.com/openai/v1/audio/transcriptions"),
        max_upload_bytes=groq_cfg.get("max_upload_bytes", 24_000_000),
        timeout_seconds=groq_cfg.get("timeout_seconds", 600.0),
    )


def _create_transcriber_for_backend(config: dict, backend: str) -> Any:
    asr_cfg = _resolve_asr_config(config)
    if backend == "remote":
        return _create_remote_transcriber(asr_cfg)
    if backend == "groq":
        return _create_groq_transcriber(asr_cfg)
    raise ValueError(f"Unknown ASR backend: {backend!r}. Supported: remote, groq")


def create_transcriber(config: dict) -> Any:
    """Create primary transcriber based on extract.asr.backend."""
    asr_cfg = _resolve_asr_config(config)
    backend = asr_cfg.get("backend", "remote")
    return _create_transcriber_for_backend(config, backend)


def create_fallback_transcriber(config: dict) -> Any | None:
    """Create optional fallback transcriber based on extract.asr.fallback_backend."""
    asr_cfg = _resolve_asr_config(config)
    fallback_backend = asr_cfg.get("fallback_backend")
    if not fallback_backend:
        return None
    return _create_transcriber_for_backend(config, fallback_backend)
