"""YouTube video subtitle and metadata extraction via yt-dlp."""

from __future__ import annotations

import contextlib
import json
import subprocess
from pathlib import Path

from yt2notion.models.base import VideoMeta


class ExtractionError(Exception):
    """Raised when yt-dlp extraction fails."""


def _run_ytdlp(args: list[str]) -> subprocess.CompletedProcess:
    """Run yt-dlp with the given arguments."""
    cmd = ["yt-dlp", *args]
    try:
        return subprocess.run(cmd, capture_output=True, text=True, check=True)
    except FileNotFoundError as e:
        raise ExtractionError(
            "yt-dlp not found. Install it: https://github.com/yt-dlp/yt-dlp#installation"
        ) from e
    except subprocess.CalledProcessError as e:
        raise ExtractionError(f"yt-dlp failed: {e.stderr.strip()}") from e


def extract_metadata(url: str) -> VideoMeta:
    """Extract video metadata using yt-dlp --dump-json."""
    from yt2notion.models.base import Chapter

    result = _run_ytdlp(["--dump-json", "--no-download", url])
    data = json.loads(result.stdout)

    chapters = [
        Chapter(
            title=ch.get("title", ""),
            start_seconds=int(ch.get("start_time", 0)),
            end_seconds=int(ch.get("end_time", 0)),
        )
        for ch in data.get("chapters") or []
    ]

    # Check subtitle availability from metadata (avoids wasted yt-dlp calls)
    subtitles_available = bool(data.get("subtitles")) or bool(data.get("automatic_captions"))

    # Channel fallback chain: channel → uploader → series (Apple Podcasts)
    channel = data.get("channel") or data.get("uploader") or data.get("series", "")

    return VideoMeta(
        video_id=data.get("id", ""),
        title=data.get("title", ""),
        channel=channel,
        upload_date=data.get("upload_date", ""),
        url=data.get("webpage_url", url),
        duration_seconds=int(data.get("duration") or 0),
        chapters=chapters,
        description=data.get("description", ""),
        language=data.get("language", ""),
        subtitles_available=subtitles_available,
        series=data.get("series", ""),
    )


def _build_subtitle_args(
    url: str,
    output_dir: Path,
    lang: str,
    *,
    auto: bool = False,
    cookies_from: str | None = None,
) -> list[str]:
    """Build yt-dlp args for subtitle download."""
    args = [
        "--skip-download",
        "--sub-lang",
        lang,
        "-o",
        str(output_dir / "%(id)s.%(ext)s"),
    ]
    if auto:
        args.append("--write-auto-sub")
    else:
        args.append("--write-sub")
    args.extend(["--sub-format", "srt"])
    args.extend(["--convert-subs", "srt"])
    if cookies_from:
        args.extend(["--cookies-from-browser", cookies_from])
    args.append(url)
    return args


def extract_subtitles(url: str, config: dict, output_dir: Path, *, video_id: str = "") -> Path:
    """Download the best available subtitle file.

    Priority: manual subs by priority list, then auto-generated fallback.
    Returns the path to the downloaded subtitle file.
    Pass video_id to avoid a redundant yt-dlp --dump-json call.
    """
    extract_cfg = config.get("extract", {})
    priority = extract_cfg.get("subtitle_priority", ["zh-Hans", "zh-Hant", "en"])
    auto_fallback = extract_cfg.get("auto_subtitle_fallback", True)
    auto_lang = extract_cfg.get("auto_subtitle_lang", "en")
    cookies_from = extract_cfg.get("cookies_from")

    if not video_id:
        meta_result = _run_ytdlp(["--dump-json", "--no-download", url])
        video_id = json.loads(meta_result.stdout).get("id", "")

    # Try manual subtitles in priority order
    for lang in priority:
        args = _build_subtitle_args(url, output_dir, lang, cookies_from=cookies_from)
        try:
            _run_ytdlp(args)
        except ExtractionError:
            continue
        # Check if file was created
        found = _find_subtitle_file(output_dir, video_id)
        if found:
            return found

    # Try auto-generated subtitles
    if auto_fallback:
        args = _build_subtitle_args(
            url, output_dir, auto_lang, auto=True, cookies_from=cookies_from
        )
        with contextlib.suppress(ExtractionError):
            _run_ytdlp(args)
        found = _find_subtitle_file(output_dir, video_id)
        if found:
            return found

    raise ExtractionError(
        f"No subtitles found for {url}. "
        f"Tried languages: {priority}" + (f" + auto ({auto_lang})" if auto_fallback else "")
    )


def extract_audio(
    url: str,
    output_dir: Path,
    *,
    video_id: str = "",
    cookies_from: str | None = None,
) -> Path:
    """Download audio using yt-dlp -x --audio-format mp3.

    Returns the path to the downloaded audio file.
    """
    args = [
        "-x",
        "--audio-format",
        "mp3",
        "-o",
        str(output_dir / "%(id)s.%(ext)s"),
    ]
    if cookies_from:
        args.extend(["--cookies-from-browser", cookies_from])
    args.append(url)
    _run_ytdlp(args)

    # Find the downloaded audio file
    audio_extensions = (".mp3", ".m4a", ".wav", ".opus", ".webm", ".ogg")
    pattern = f"{video_id}*" if video_id else "*"
    for candidate in sorted(output_dir.glob(pattern), key=lambda p: p.stat().st_size, reverse=True):
        if candidate.suffix in audio_extensions:
            return candidate

    raise ExtractionError(f"Audio download succeeded but file not found in {output_dir}")


def _find_subtitle_file(output_dir: Path, video_id: str) -> Path | None:
    """Find a downloaded subtitle file in the output directory."""
    for ext in ("srt", "vtt"):
        candidates = list(output_dir.glob(f"{video_id}*.{ext}"))
        if candidates:
            return candidates[0]
    return None
