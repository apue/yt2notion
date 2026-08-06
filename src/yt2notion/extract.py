"""YouTube video subtitle and metadata extraction via yt-dlp."""

from __future__ import annotations

import html
import json
import re
import subprocess
from pathlib import Path
from urllib.parse import urljoin

import httpx

from yt2notion.models.base import VideoMeta
from yt2notion.process import SubtitleEntry


class ExtractionError(Exception):
    """Raised when yt-dlp extraction fails."""


_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/137.0.0.0 Safari/537.36"
    )
}


def _run_ytdlp(args: list[str]) -> subprocess.CompletedProcess:
    """Run yt-dlp with the given arguments."""
    cmd = ["yt-dlp", "--no-playlist", *args]
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

    manual_subtitle_languages = list((data.get("subtitles") or {}).keys())
    automatic_caption_languages = list((data.get("automatic_captions") or {}).keys())

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
        manual_subtitle_languages=manual_subtitle_languages,
        automatic_caption_languages=automatic_caption_languages,
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


def _download_subtitle_track(
    url: str,
    output_dir: Path,
    lang: str,
    *,
    auto: bool,
    cookies_from: str | None,
) -> None:
    """Download a public track first, retrying with browser cookies only if needed."""
    args = _build_subtitle_args(url, output_dir, lang, auto=auto)
    try:
        _run_ytdlp(args)
    except ExtractionError:
        if not cookies_from:
            raise
        _run_ytdlp(
            _build_subtitle_args(
                url,
                output_dir,
                lang,
                auto=auto,
                cookies_from=cookies_from,
            )
        )


def extract_subtitles(url: str, config: dict, output_dir: Path, *, metadata: VideoMeta) -> Path:
    """Download the best available subtitle file.

    Priority: manual subs by priority list, then auto-generated fallback.
    Returns the path to the downloaded subtitle file.
    Metadata from the acquisition probe selects one available language.
    """
    path, _source = extract_subtitles_with_source(url, config, output_dir, metadata=metadata)
    return path


def extract_subtitles_with_source(
    url: str, config: dict, output_dir: Path, *, metadata: VideoMeta
) -> tuple[Path, str]:
    """Download subtitles and return both file path and transcript source marker.

    Source is ``manual_subtitle`` for explicit subtitles and ``auto_caption`` for
    yt-dlp automatic captions so downstream cleanup can distinguish them.
    """
    extract_cfg = config.get("extract", {})
    priority = extract_cfg.get("subtitle_priority", ["zh-Hans", "zh-Hant", "en"])
    auto_fallback = extract_cfg.get("auto_subtitle_fallback", True)
    auto_lang = extract_cfg.get("auto_subtitle_lang", "en")
    cookies_from = extract_cfg.get("cookies_from")

    manual_lang = next(
        (lang for lang in priority if lang in metadata.manual_subtitle_languages),
        None,
    )
    if manual_lang:
        _download_subtitle_track(
            url,
            output_dir,
            manual_lang,
            auto=False,
            cookies_from=cookies_from,
        )
        found = _find_subtitle_file(output_dir, metadata.video_id)
        if found:
            return found, "manual_subtitle"

    if auto_fallback and auto_lang in metadata.automatic_caption_languages:
        _download_subtitle_track(
            url,
            output_dir,
            auto_lang,
            auto=True,
            cookies_from=cookies_from,
        )
        found = _find_subtitle_file(output_dir, metadata.video_id)
        if found:
            return found, "auto_caption"

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


def extract_video(
    url: str,
    output_dir: Path,
    *,
    video_id: str = "",
    cookies_from: str | None = None,
) -> Path:
    """Download a playable video file using yt-dlp.

    Returns the path to the downloaded video file.
    """
    args = [
        "-f",
        "bestvideo*+bestaudio/best",
        "--merge-output-format",
        "mp4",
        "-o",
        str(output_dir / "%(id)s.%(ext)s"),
    ]
    if cookies_from:
        args.extend(["--cookies-from-browser", cookies_from])
    args.append(url)
    _run_ytdlp(args)

    video_extensions = (".mp4", ".mkv", ".webm", ".mov", ".m4v")
    pattern = f"{video_id}*" if video_id else "*"
    for candidate in sorted(output_dir.glob(pattern), key=lambda p: p.stat().st_size, reverse=True):
        if candidate.suffix in video_extensions:
            return candidate

    raise ExtractionError(f"Video download succeeded but file not found in {output_dir}")


def extract_webpage_transcript(url: str, metadata: VideoMeta) -> list[SubtitleEntry]:
    """Extract a transcript from the source page or a linked episode webpage."""
    page_html = _fetch_page(url)

    candidates = [url]
    candidates.extend(_find_episode_webpage_candidates(page_html, base_url=url))

    seen: set[str] = set()
    for candidate in candidates:
        if candidate in seen:
            continue
        seen.add(candidate)

        html_text = page_html if candidate == url else _fetch_page(candidate)
        paragraphs = _extract_transcript_paragraphs(html_text)
        if paragraphs:
            return _build_transcript_entries(paragraphs, metadata.duration_seconds)

    return []


def write_transcript_srt(entries: list[SubtitleEntry], output_path: Path) -> Path:
    """Write transcript entries to an SRT file."""
    lines: list[str] = []
    for index, entry in enumerate(entries, start=1):
        lines.extend(
            [
                str(index),
                f"{_format_srt_timestamp(entry.start_seconds)} --> "
                f"{_format_srt_timestamp(entry.end_seconds)}",
                entry.text,
                "",
            ]
        )

    output_path.write_text("\n".join(lines), encoding="utf-8")
    return output_path


def _find_subtitle_file(output_dir: Path, video_id: str) -> Path | None:
    """Find a downloaded subtitle file in the output directory."""
    for ext in ("srt", "vtt"):
        candidates = list(output_dir.glob(f"{video_id}*.{ext}"))
        if candidates:
            return candidates[0]
    return None


def _fetch_page(url: str) -> str:
    """Fetch a webpage as text."""
    response = httpx.get(url, headers=_HTTP_HEADERS, follow_redirects=True, timeout=30.0)
    response.raise_for_status()
    return response.text


def _find_episode_webpage_candidates(page_html: str, *, base_url: str) -> list[str]:
    """Find likely episode webpage links from a landing page."""
    matches: list[str] = []
    for match in re.finditer(
        r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        href, inner_html = match.groups()
        if "episode webpage" not in _html_to_text(inner_html).lower():
            continue
        matches.append(urljoin(base_url, href))
    return matches


def _extract_transcript_paragraphs(page_html: str) -> list[str]:
    """Extract transcript paragraphs from a webpage transcript section."""
    transcript_marker = re.search(
        r'<div[^>]+id="transcript"[^>]*>.*?</div>\s*<div[^>]+class="[^"]*rich-text-block-6[^"]*"[^>]*>(.*?)</div>',
        page_html,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not transcript_marker:
        return []

    content_html = transcript_marker.group(1)
    paragraphs = re.findall(r"<p>(.*?)</p>", content_html, flags=re.IGNORECASE | re.DOTALL)

    cleaned: list[str] = []
    for paragraph in paragraphs:
        text = _html_to_text(paragraph)
        if text:
            cleaned.append(text)
    return cleaned


def _html_to_text(fragment: str) -> str:
    """Convert a simple HTML fragment into readable text."""
    fragment = re.sub(r"<br\s*/?>", "\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"</p>\s*<p>", "\n\n", fragment, flags=re.IGNORECASE)
    fragment = re.sub(r"<[^>]+>", "", fragment)
    text = html.unescape(fragment)
    text = text.replace("\xa0", " ")
    text = text.replace("\u200d", "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _build_transcript_entries(
    paragraphs: list[str], duration_seconds: int | float | None
) -> list[SubtitleEntry]:
    """Assign approximate timestamps across transcript paragraphs."""
    cleaned = [paragraph for paragraph in paragraphs if paragraph]
    if not cleaned:
        return []

    total_duration = float(duration_seconds or len(cleaned))
    step = max(1.0, total_duration / len(cleaned))

    entries: list[SubtitleEntry] = []
    for index, paragraph in enumerate(cleaned):
        start = index * step
        end = min(total_duration, (index + 1) * step)
        if end <= start:
            end = start + 1.0
        entries.append(
            SubtitleEntry(
                start_seconds=start,
                end_seconds=end,
                text=paragraph,
            )
        )
    return entries


def _format_srt_timestamp(seconds: float) -> str:
    """Format seconds in SRT timestamp format."""
    total_millis = max(0, int(seconds * 1000))
    hours, remainder = divmod(total_millis, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, millis = divmod(remainder, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{millis:03d}"
