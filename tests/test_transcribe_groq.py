"""Tests for GroqTranscriber backend."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from yt2notion.transcribe.errors import (
    TranscriptionError,
    TranscriptionQuotaError,
    TranscriptionServerError,
)
from yt2notion.transcribe.groq import GroqTranscriber


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)


def _make_audio(tmp_path: Path, size: int = 1024) -> Path:
    p = tmp_path / "audio.mp3"
    p.write_bytes(b"\x00" * size)
    return p


def _http_response(status: int, *, json_body=None, text: str = "") -> httpx.Response:
    req = httpx.Request("POST", "http://x")
    if json_body is not None:
        resp = httpx.Response(status, json=json_body, request=req)
    else:
        resp = httpx.Response(status, text=text, request=req)
    return resp


def test_success_parses_segments(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    body = {
        "segments": [
            {"start": 0.0, "end": 1.5, "text": "  hello  "},
            {"start": 1.5, "end": 2.0, "text": "   "},
            {"start": 2.0, "end": 3.0, "text": "world"},
        ]
    }

    def fake_post(*args, **kwargs):
        return _http_response(200, json_body=body)

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)

    t = GroqTranscriber(api_key="sk-test")
    result = t.transcribe(audio)
    assert len(result) == 2
    assert result[0].text == "hello"
    assert result[0].start_seconds == 0.0
    assert result[1].text == "world"


def test_empty_segments_returns_empty_list(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(200, json_body={"segments": []}),
    )
    assert GroqTranscriber(api_key="k").transcribe(audio) == []


def test_missing_segments_field_returns_empty(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(200, json_body={}),
    )
    assert GroqTranscriber(api_key="k").transcribe(audio) == []


def test_429_raises_quota_error(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _http_response(429, json_body={"error": "rate"})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    with pytest.raises(TranscriptionQuotaError):
        GroqTranscriber(api_key="k").transcribe(audio)
    # quota error is not retryable, should be called only once
    assert len(calls) == 1


def test_500_after_retries_raises_server_error(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _http_response(500, json_body={"error": "boom"})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    with pytest.raises(TranscriptionServerError):
        GroqTranscriber(api_key="k").transcribe(audio)
    assert len(calls) == 3


def test_401_raises_transcription_error_not_subclass(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(401, json_body={"error": "auth"}),
    )
    with pytest.raises(TranscriptionError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert not isinstance(exc.value, TranscriptionQuotaError)
    assert not isinstance(exc.value, TranscriptionServerError)


def test_400_raises_transcription_error(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(400, json_body={"error": "bad"}),
    )
    with pytest.raises(TranscriptionError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert not isinstance(exc.value, TranscriptionQuotaError)
    assert not isinstance(exc.value, TranscriptionServerError)


def test_oversized_file_raises_before_http(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path, size=200)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    t = GroqTranscriber(api_key="k", max_upload_bytes=100)
    with pytest.raises(TranscriptionError):
        t.transcribe(audio)
    assert calls == []


def test_language_threaded_through(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    captured: dict = {}

    def fake_post(url, *, files, data, headers, timeout):
        captured["data"] = data
        captured["headers"] = headers
        captured["url"] = url
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    GroqTranscriber(api_key="k").transcribe(audio, language="en")
    assert captured["data"]["language"] == "en"
    assert captured["data"]["model"] == "whisper-large-v3-turbo"
    assert captured["data"]["response_format"] == "verbose_json"


def test_api_key_in_auth_header(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    captured: dict = {}

    def fake_post(url, *, files, data, headers, timeout):
        captured["headers"] = headers
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    GroqTranscriber(api_key="sk-test").transcribe(audio)
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_invalid_json_raises_transcription_error(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(200, text="not json"),
    )
    with pytest.raises(TranscriptionError):
        GroqTranscriber(api_key="k").transcribe(audio)
