"""Standalone extraction entry point for Claude Code slash command.

Usage: uv run python -m yt2notion.extract_cmd "YOUTUBE_URL"

Outputs JSON with metadata + formatted transcript to stdout.
"""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from yt2notion.config import DEFAULTS, ConfigError, load_config
from yt2notion.extract import extract_metadata, extract_subtitles
from yt2notion.process import (
    format_chapters_transcript,
    format_timestamped_transcript,
    parse_subtitle_file,
)


def _load_extract_config(config_path: str) -> dict:
    """Load extract config from YAML, falling back to defaults if file is missing."""
    try:
        config = load_config(config_path)
        return {"extract": config.extract}
    except ConfigError:
        return {"extract": DEFAULTS["extract"]}


def main() -> None:
    if len(sys.argv) < 2:
        print("Usage: python -m yt2notion.extract_cmd <youtube_url> [config_path]", file=sys.stderr)
        sys.exit(1)

    url = sys.argv[1]
    config_path = sys.argv[2] if len(sys.argv) > 2 else "config.yaml"
    raw_config = _load_extract_config(config_path)

    # 1. Extract metadata
    metadata = extract_metadata(url)

    # 2. Extract and parse subtitles
    with tempfile.TemporaryDirectory() as tmp_dir:
        subtitle_path = extract_subtitles(
            url, raw_config, Path(tmp_dir), video_id=metadata.video_id
        )
        entries = parse_subtitle_file(subtitle_path)

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
    }
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
