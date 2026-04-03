"""Tests for the transcription module."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from yt2notion.transcribe import create_transcriber
from yt2notion.transcribe.remote import RemoteTranscriber, TranscriptionError


class TestRemoteTranscriber:
    def test_transcribe_parses_segments(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake audio data")

        mock_response = {
            "segments": [
                {"start": 0.0, "end": 3.2, "text": "Hello world"},
                {"start": 3.2, "end": 6.5, "text": "This is a test"},
                {"start": 6.5, "end": 6.5, "text": "  "},  # empty, should be filtered
            ]
        }

        with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
            mock_post.return_value.json.return_value = mock_response
            mock_post.return_value.raise_for_status = lambda: None

            transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
            entries = transcriber.transcribe(audio_file)

        assert len(entries) == 2
        assert entries[0].start_seconds == 0.0
        assert entries[0].end_seconds == 3.2
        assert entries[0].text == "Hello world"
        assert entries[1].text == "This is a test"

    def test_transcribe_sends_language(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
            mock_post.return_value.json.return_value = {"segments": []}
            mock_post.return_value.raise_for_status = lambda: None

            transcriber = RemoteTranscriber(endpoint="http://localhost:8930/")
            transcriber.transcribe(audio_file, language="zh")

        call_kwargs = mock_post.call_args
        assert call_kwargs.kwargs["data"]["language"] == "zh"
        assert call_kwargs.kwargs["timeout"] == 1800.0

    def test_transcribe_http_error(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        import httpx

        with patch("yt2notion.transcribe.remote.httpx.post") as mock_post:
            mock_post.side_effect = httpx.ConnectError("Connection refused")

            transcriber = RemoteTranscriber(endpoint="http://localhost:8930")
            with pytest.raises(TranscriptionError, match="ASR request failed"):
                transcriber.transcribe(audio_file)

    def test_endpoint_trailing_slash_stripped(self):
        t = RemoteTranscriber(endpoint="http://localhost:8930/")
        assert t.endpoint == "http://localhost:8930"

    def test_restart_before_transcribe_runs_once(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        request = {"segments": [{"start": 0.0, "end": 1.0, "text": "ok"}]}

        with (
            patch("yt2notion.transcribe.remote.subprocess.run") as mock_restart,
            patch("yt2notion.transcribe.remote.httpx.get") as mock_get,
            patch("yt2notion.transcribe.remote.httpx.post") as mock_post,
        ):
            mock_get.return_value.status_code = 200
            mock_post.return_value.json.return_value = request
            mock_post.return_value.raise_for_status = lambda: None

            transcriber = RemoteTranscriber(
                endpoint="http://localhost:8930",
                restart_before_transcribe=True,
                restart_command="echo restart",
            )
            transcriber.transcribe(audio_file)
            transcriber.transcribe(audio_file)

        assert mock_restart.call_count == 1
        assert mock_post.call_count == 2

    def test_restart_on_unhealthy(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        with (
            patch("yt2notion.transcribe.remote.subprocess.run") as mock_restart,
            patch("yt2notion.transcribe.remote.httpx.get") as mock_get,
            patch("yt2notion.transcribe.remote.httpx.post") as mock_post,
        ):
            # First health check unhealthy, post-restart healthy.
            mock_get.side_effect = [
                type("Resp", (), {"status_code": 503})(),
                type("Resp", (), {"status_code": 200})(),
            ]
            mock_post.return_value.json.return_value = {"segments": []}
            mock_post.return_value.raise_for_status = lambda: None

            transcriber = RemoteTranscriber(
                endpoint="http://localhost:8930",
                restart_on_unhealthy=True,
                restart_command="echo restart",
            )
            transcriber.transcribe(audio_file)

        assert mock_restart.call_count == 1

    def test_restart_enabled_without_command_raises(self, tmp_path: Path):
        audio_file = tmp_path / "test.mp3"
        audio_file.write_bytes(b"fake")

        transcriber = RemoteTranscriber(
            endpoint="http://localhost:8930",
            restart_before_transcribe=True,
            restart_command="",
        )

        with pytest.raises(TranscriptionError, match="restart_command is empty"):
            transcriber.transcribe(audio_file)


class TestCreateTranscriber:
    def test_remote_backend(self):
        config = {"extract": {"asr": {"backend": "remote", "endpoint": "http://localhost:8930"}}}
        t = create_transcriber(config)
        assert isinstance(t, RemoteTranscriber)

    def test_env_var_fallback(self, monkeypatch):
        monkeypatch.setenv("ASR_ENDPOINT", "http://env-host:8930")
        config = {"extract": {"asr": {"backend": "remote", "endpoint": ""}}}
        t = create_transcriber(config)
        assert isinstance(t, RemoteTranscriber)
        assert t.endpoint == "http://env-host:8930"

    def test_no_endpoint_raises(self, monkeypatch):
        monkeypatch.delenv("ASR_ENDPOINT", raising=False)
        config = {"extract": {"asr": {"backend": "remote", "endpoint": ""}}}
        with pytest.raises(ValueError, match="ASR endpoint required"):
            create_transcriber(config)

    def test_unknown_backend_raises(self):
        config = {"extract": {"asr": {"backend": "unknown", "endpoint": "http://x"}}}
        with pytest.raises(ValueError, match="Unknown ASR backend"):
            create_transcriber(config)

    def test_remote_backend_with_restart_options(self):
        config = {
            "extract": {
                "asr": {
                    "backend": "remote",
                    "endpoint": "http://localhost:8930",
                    "healthcheck_path": "/healthz",
                    "restart_before_transcribe": True,
                    "restart_on_unhealthy": True,
                    "restart_command": "echo restart",
                    "restart_grace_seconds": 1.0,
                }
            }
        }
        t = create_transcriber(config)
        assert isinstance(t, RemoteTranscriber)
        assert t.healthcheck_path == "/healthz"
        assert t.restart_before_transcribe is True
        assert t.restart_on_unhealthy is True
        assert t.restart_command == "echo restart"
        assert t.restart_grace_seconds == 1.0
