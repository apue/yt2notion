"""Focused retry tests for the remote ASR transcriber."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
import pytest

import yt2notion.retry as retry_module
from yt2notion.transcribe.remote import RemoteTranscriber, TranscriptionError


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(retry_module.time, "sleep", lambda _: None)


def _make_request() -> httpx.Request:
    return httpx.Request("POST", "http://localhost:8930/transcribe")


def _make_audio_file(tmp_path: Path) -> Path:
    audio_file = tmp_path / "test.mp3"
    audio_file.write_bytes(b"fake audio data")
    return audio_file


def test_transcribe_retries_connect_error_then_succeeds(tmp_path: Path) -> None:
    audio_file = _make_audio_file(tmp_path)
    request = _make_request()
    success_response = httpx.Response(
        200,
        request=request,
        json={"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]},
    )

    with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
        mock_post.side_effect = [httpx.ConnectError("connection refused"), success_response]

        transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
        entries = transcriber.transcribe(audio_file)

    assert len(entries) == 1
    assert entries[0].text == "hello"
    assert mock_post.call_count == 2


def test_transcribe_retries_5xx_then_succeeds(tmp_path: Path) -> None:
    audio_file = _make_audio_file(tmp_path)
    request = _make_request()
    success_response = httpx.Response(
        200,
        request=request,
        json={"segments": [{"start": 0.0, "end": 1.0, "text": "hello"}]},
    )

    with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
        mock_post.side_effect = [httpx.Response(503, request=request), success_response]

        transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
        entries = transcriber.transcribe(audio_file)

    assert len(entries) == 1
    assert entries[0].text == "hello"
    assert mock_post.call_count == 2


def test_transcribe_exhausts_retries_on_connect_error(tmp_path: Path) -> None:
    audio_file = _make_audio_file(tmp_path)

    with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
        mock_post.side_effect = httpx.ConnectError("connection refused")

        transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
        with pytest.raises(TranscriptionError, match="ASR request failed"):
            transcriber.transcribe(audio_file)

    assert mock_post.call_count == 3


def test_transcribe_4xx_fails_immediately(tmp_path: Path) -> None:
    audio_file = _make_audio_file(tmp_path)
    request = _make_request()

    with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
        mock_post.return_value = httpx.Response(400, request=request)

        transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
        with pytest.raises(TranscriptionError, match="ASR request failed"):
            transcriber.transcribe(audio_file)

    assert mock_post.call_count == 1


def test_transcribe_json_decode_error_fails_immediately(tmp_path: Path) -> None:
    audio_file = _make_audio_file(tmp_path)
    bad_response = Mock(spec=httpx.Response)
    bad_response.raise_for_status.return_value = None
    bad_response.json.side_effect = json.JSONDecodeError("Expecting value", "not json", 0)

    with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
        mock_post.return_value = bad_response

        transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
        with pytest.raises(TranscriptionError, match="not valid JSON"):
            transcriber.transcribe(audio_file)

    assert mock_post.call_count == 1
