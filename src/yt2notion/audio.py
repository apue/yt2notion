"""Audio utilities: duration detection and segment splitting via ffmpeg/ffprobe."""

from __future__ import annotations

import subprocess
from pathlib import Path


class AudioError(Exception):
    """Raised when ffmpeg/ffprobe operations fail."""


def get_duration(audio_path: Path) -> float:
    """Get audio duration in seconds via ffprobe."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "csv=p=0",
        str(audio_path),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return float(result.stdout.strip())
    except FileNotFoundError as e:
        raise AudioError("ffprobe not found. Install ffmpeg.") from e
    except (subprocess.CalledProcessError, ValueError) as e:
        raise AudioError(f"Failed to get duration for {audio_path}: {e}") from e


def split_audio(
    audio_path: Path,
    segments: list[dict],
    output_dir: Path,
) -> list[Path]:
    """Split audio into per-segment files via ffmpeg.

    Each segment dict must have 'start_seconds' and 'end_seconds' keys.
    Adds 0.5s padding at boundaries to avoid cutting mid-word.
    Uses stream copy (-c copy) for speed.

    Returns list of output file paths in segment order.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = audio_path.suffix or ".mp3"
    outputs: list[Path] = []

    for i, seg in enumerate(segments):
        start = max(0, seg["start_seconds"] - 0.5)
        end = seg["end_seconds"] + 0.5
        out_path = output_dir / f"segment_{i + 1:03d}{suffix}"

        cmd = [
            "ffmpeg",
            "-y",
            "-i",
            str(audio_path),
            "-ss",
            str(start),
            "-to",
            str(end),
            "-c",
            "copy",
            str(out_path),
        ]
        try:
            subprocess.run(cmd, capture_output=True, text=True, check=True)
        except FileNotFoundError as e:
            raise AudioError("ffmpeg not found. Install ffmpeg.") from e
        except subprocess.CalledProcessError as e:
            raise AudioError(f"Failed to split segment {i + 1}: {e.stderr.strip()}") from e

        outputs.append(out_path)

    return outputs
