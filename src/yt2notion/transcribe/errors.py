"""Exceptions for the transcribe subsystem."""

from __future__ import annotations


class TranscriptionError(Exception):
    """Raised when ASR transcription fails."""


class TranscriptionQuotaError(TranscriptionError):
    """Raised when an ASR backend is rate-limited or out of quota (e.g. HTTP 429).

    Pipeline-level callers may catch this to fall back to another backend.
    """


class TranscriptionServerError(TranscriptionError):
    """Raised when an ASR backend returns 5xx after retries are exhausted.

    Pipeline-level callers may catch this to fall back to another backend.
    """
