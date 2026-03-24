"""Tests for audio utilities."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from yt2notion.audio import AudioError, get_duration, split_audio


@patch("yt2notion.audio.subprocess.run")
def test_get_duration(mock_run, tmp_path):
    mock_run.return_value.stdout = "123.45\n"
    mock_run.return_value.returncode = 0

    result = get_duration(tmp_path / "test.mp3")
    assert result == 123.45
    mock_run.assert_called_once()


@patch("yt2notion.audio.subprocess.run")
def test_get_duration_error(mock_run, tmp_path):
    import subprocess

    mock_run.side_effect = subprocess.CalledProcessError(1, "ffprobe")

    with pytest.raises(AudioError, match="Failed to get duration"):
        get_duration(tmp_path / "test.mp3")


@patch("yt2notion.audio.subprocess.run")
def test_split_audio(mock_run, tmp_path):
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"fake")
    out_dir = tmp_path / "segments"

    segments = [
        {"start_seconds": 0, "end_seconds": 300},
        {"start_seconds": 300, "end_seconds": 600},
    ]

    # Make split create output files
    def side_effect(cmd, **kwargs):
        out_path = cmd[-1]
        open(out_path, "w").close()
        return type("Result", (), {"returncode": 0})()

    mock_run.side_effect = side_effect

    result = split_audio(audio, segments, out_dir)
    assert len(result) == 2
    assert result[0].name == "segment_001.mp3"
    assert result[1].name == "segment_002.mp3"
    assert mock_run.call_count == 2


@patch("yt2notion.audio.subprocess.run")
def test_split_audio_padding(mock_run, tmp_path):
    """Verify 0.5s padding at boundaries."""
    audio = tmp_path / "test.mp3"
    audio.write_bytes(b"fake")

    def side_effect(cmd, **kwargs):
        open(cmd[-1], "w").close()
        return type("Result", (), {"returncode": 0})()

    mock_run.side_effect = side_effect

    split_audio(audio, [{"start_seconds": 10, "end_seconds": 60}], tmp_path / "out")

    call_args = mock_run.call_args[0][0]
    ss_idx = call_args.index("-ss")
    to_idx = call_args.index("-to")
    assert call_args[ss_idx + 1] == "9.5"  # 10 - 0.5
    assert call_args[to_idx + 1] == "60.5"  # 60 + 0.5
