"""Standalone extraction entry point for Claude Code slash command.

Usage: uv run python -m yt2notion.extract_cmd "URL"

Outputs JSON with metadata + formatted transcript to stdout.
Uses metadata-driven flow: checks subtitles availability before attempting download.
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from yt2notion.config import DEFAULTS, ConfigError, load_config
from yt2notion.extract import ExtractionError, extract_audio, extract_metadata, extract_subtitles
from yt2notion.process import (
    format_chapters_transcript,
    format_timestamped_transcript,
    parse_subtitle_file,
)

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.process import SubtitleEntry


def _load_extract_config(config_path: str) -> dict:
    """Load extract config from YAML, falling back to defaults if file is missing."""
    try:
        config = load_config(config_path)
        return {"extract": config.extract, "model": config.model}
    except ConfigError:
        return {"extract": DEFAULTS["extract"], "model": DEFAULTS["model"]}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m yt2notion.extract_cmd <url> [config_path]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    config_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"
    raw_config = _load_extract_config(config_path)

    # 1. Extract metadata
    metadata = extract_metadata(url)

    # 2. Metadata-driven: check subtitles availability
    source = "subtitles"
    with tempfile.TemporaryDirectory() as tmp_dir:
        if metadata.subtitles_available:
            try:
                subtitle_path = extract_subtitles(
                    url, raw_config, Path(tmp_dir), video_id=metadata.video_id
                )
                entries = parse_subtitle_file(subtitle_path)
            except ExtractionError:
                # Subtitles metadata said available but download failed — try ASR
                entries = _fallback_asr(url, metadata, raw_config, Path(tmp_dir))
                source = "asr"
        else:
            # No subtitles — go straight to ASR
            entries = _fallback_asr(url, metadata, raw_config, Path(tmp_dir))
            source = "asr"

    # 3. Build transcript based on chapters
    if metadata.chapters:
        transcript = format_chapters_transcript(entries, metadata.chapters)
        prompt_mode = "chapters"
    else:
        transcript = format_timestamped_transcript(entries)
        prompt_mode = "freeform"

    # 4. Output structured JSON
    result = {
        "metadata": {
            "video_id": metadata.video_id,
            "title": metadata.title,
            "channel": metadata.channel,
            "upload_date": metadata.upload_date,
            "url": metadata.url,
            "duration_seconds": metadata.duration_seconds,
            "chapter_count": len(metadata.chapters),
        },
        "transcript": transcript,
        "prompt_mode": prompt_mode,
        "subtitle_entries": len(entries),
        "source": source,
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


def _fallback_asr(
    url: str, metadata: VideoMeta, raw_config: dict, tmp_dir: Path
) -> list[SubtitleEntry]:
    """Download audio and transcribe via ASR."""
    asr_cfg = raw_config.get("extract", {}).get("asr", {})
    endpoint = asr_cfg.get("endpoint", "") or os.environ.get("ASR_ENDPOINT", "")
    if not endpoint:
        raise ExtractionError("No subtitles and no ASR endpoint configured")

    from yt2notion.transcribe import create_transcriber

    print("No subtitles — falling back to ASR...", file=sys.stderr)
    cookies_from = raw_config.get("extract", {}).get("cookies_from")
    audio_path = extract_audio(url, tmp_dir, video_id=metadata.video_id, cookies_from=cookies_from)
    transcriber = create_transcriber(raw_config)
    return transcriber.transcribe(audio_path, language=metadata.language or None)


if __name__ == "__main__":
    main()
