"""Tests for GroqTranscriber backend."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from yt2notion.transcribe.errors import (
    TranscriptionDailyLimitError,
    TranscriptionError,
    TranscriptionHourlyLimitError,
    TranscriptionQuotaError,
    TranscriptionServerError,
)
from yt2notion.transcribe.groq import GroqTranscriber


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda *a, **k: None)


def _make_audio(tmp_path: Path, size: int = 1024, filename: str = "audio.mp3") -> Path:
    p = tmp_path / filename
    p.write_bytes(b"\x00" * size)
    return p


def _http_response(
    status: int,
    *,
    json_body=None,
    text: str = "",
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    req = httpx.Request("POST", "http://x")
    if json_body is not None:
        resp = httpx.Response(status, json=json_body, headers=headers, request=req)
    else:
        resp = httpx.Response(status, text=text, headers=headers, request=req)
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


def test_429_with_retry_after_raises_hourly_limit(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    calls = []

    def fake_post(*a, **k):
        calls.append(1)
        return _http_response(
            429,
            json_body={"error": {"message": "rate limit"}},
            headers={"retry-after": "120"},
        )

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    with pytest.raises(TranscriptionHourlyLimitError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert exc.value.retry_after_seconds == 120
    # quota error is not retryable, should be called only once
    assert len(calls) == 1


def test_429_without_hint_defaults_to_hourly_limit(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(429, json_body={"error": "rate"}),
    )
    with pytest.raises(TranscriptionQuotaError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert isinstance(exc.value, TranscriptionHourlyLimitError)
    assert exc.value.retry_after_seconds == 3600


def test_429_with_invalid_retry_after_defaults_to_hourly_limit(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(
            429,
            json_body={"error": {"message": "rate limit"}},
            headers={"retry-after": "not-a-number"},
        ),
    )
    with pytest.raises(TranscriptionHourlyLimitError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert exc.value.retry_after_seconds == 3600


def test_429_daily_limit_message_raises_daily_limit(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(
            429,
            json_body={"error": {"message": "Daily quota exceeded for today"}},
        ),
    )
    with pytest.raises(TranscriptionDailyLimitError):
        GroqTranscriber(api_key="k").transcribe(audio)


def test_429_today_message_without_daily_phrase_stays_hourly(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path)
    monkeypatch.setattr(
        "yt2notion.transcribe.groq.httpx.post",
        lambda *a, **k: _http_response(
            429,
            json_body={"error": {"message": "Rate limit hit today, retry after 60 seconds"}},
        ),
    )
    with pytest.raises(TranscriptionHourlyLimitError):
        GroqTranscriber(api_key="k").transcribe(audio)


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


def test_multipart_m4a_uses_audio_mp4_mime(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path, filename="episode.m4a")
    captured: dict = {}

    def fake_post(url, *, files, data, headers, timeout):
        captured["file_payload"] = files["file"]
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    GroqTranscriber(api_key="k").transcribe(audio)

    payload = captured["file_payload"]
    assert payload[0] == "episode.m4a"
    assert payload[2] == "audio/mp4"


def test_multipart_mp3_uses_audio_mpeg_mime(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path, filename="episode.mp3")
    captured: dict = {}

    def fake_post(url, *, files, data, headers, timeout):
        captured["file_payload"] = files["file"]
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    GroqTranscriber(api_key="k").transcribe(audio)

    payload = captured["file_payload"]
    assert payload[0] == "episode.mp3"
    assert payload[2] == "audio/mpeg"


def test_multipart_unknown_suffix_omits_or_uses_octet_stream(tmp_path, monkeypatch):
    audio = _make_audio(tmp_path, filename="episode.foo")
    captured: dict = {}

    def fake_post(url, *, files, data, headers, timeout):
        captured["file_payload"] = files["file"]
        return _http_response(200, json_body={"segments": []})

    monkeypatch.setattr("yt2notion.transcribe.groq.httpx.post", fake_post)
    GroqTranscriber(api_key="k").transcribe(audio)

    payload = captured["file_payload"]
    assert payload[0] == "episode.foo"
    if len(payload) == 3:
        assert payload[2] == "application/octet-stream"
