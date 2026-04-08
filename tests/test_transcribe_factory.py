"""Tests for ASR transcriber factory wiring."""

from __future__ import annotations

import pytest

from yt2notion.transcribe import create_fallback_transcriber, create_transcriber


def test_create_transcriber_remote_backend_with_endpoint() -> None:
    transcriber = create_transcriber(
        {
            "extract": {
                "asr": {
                    "backend": "remote",
                    "endpoint": "http://localhost:8930",
                }
            }
        }
    )

    assert transcriber.endpoint == "http://localhost:8930"


def test_create_transcriber_groq_uses_env_api_key_when_config_empty(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "sk-env")
    config = {
        "extract": {
            "asr": {
                "backend": "groq",
                "groq": {
                    "api_key": "",
                    "model": "whisper-large-v3-turbo",
                    "max_upload_bytes": 12_345,
                    "endpoint": "https://api.groq.com/openai/v1/audio/transcriptions",
                    "timeout_seconds": 123,
                },
            }
        }
    }

    transcriber = create_transcriber(config)

    assert transcriber.api_key == "sk-env"
    assert transcriber.max_upload_bytes == 12_345


def test_create_fallback_transcriber_returns_none_when_not_configured() -> None:
    assert create_fallback_transcriber({"extract": {"asr": {"backend": "remote"}}}) is None


def test_create_fallback_transcriber_uses_fallback_backend() -> None:
    config = {
        "extract": {
            "asr": {
                "backend": "groq",
                "fallback_backend": "remote",
                "endpoint": "http://localhost:8930",
                "groq": {"api_key": "sk-test"},
            }
        }
    }

    fallback = create_fallback_transcriber(config)

    assert fallback is not None
    assert fallback.endpoint == "http://localhost:8930"


def test_create_fallback_transcriber_uses_env_for_remote_endpoint(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ASR_ENDPOINT", "http://env-asr:8930")
    config = {
        "extract": {
            "asr": {
                "backend": "groq",
                "fallback_backend": "remote",
                "endpoint": "",
                "groq": {"api_key": "sk-test"},
            }
        }
    }

    fallback = create_fallback_transcriber(config)

    assert fallback is not None
    assert fallback.endpoint == "http://env-asr:8930"


def test_create_transcriber_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown ASR backend"):
        create_transcriber({"extract": {"asr": {"backend": "unknown"}}})


def test_create_fallback_transcriber_unknown_backend_raises() -> None:
    with pytest.raises(ValueError, match="Unknown ASR backend"):
        create_fallback_transcriber(
            {
                "extract": {
                    "asr": {
                        "backend": "remote",
                        "fallback_backend": "unknown",
                        "endpoint": "http://localhost:8930",
                    }
                }
            }
        )


def test_create_transcriber_groq_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    with pytest.raises(ValueError, match="GROQ API key required"):
        create_transcriber({"extract": {"asr": {"backend": "groq", "groq": {"api_key": ""}}}})
