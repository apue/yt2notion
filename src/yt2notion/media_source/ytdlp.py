"""yt-dlp backed MediaSource adapter."""

from __future__ import annotations

import hashlib
import tempfile
from pathlib import Path

import typer

from yt2notion.audio import extract_audio_from_video, get_duration
from yt2notion.extract import (
    ExtractionError,
    extract_audio,
    extract_metadata,
    extract_subtitles_with_source,
    extract_video,
    extract_webpage_transcript,
    write_transcript_srt,
)
from yt2notion.media_source.base import (
    MediaAcquireRequest,
    MediaAcquireResult,
    MediaAcquisitionError,
)
from yt2notion.process import seconds_to_display
from yt2notion.workspace import Workspace


class YtDlpMediaSource:
    """Acquire media through the existing yt-dlp extraction implementation."""

    def __init__(self, config: dict, *, verbose: bool = False) -> None:
        self.config = config
        self.verbose = verbose

    def acquire(self, request: MediaAcquireRequest) -> MediaAcquireResult:
        """Acquire metadata, preferring subtitles over media download and ASR."""
        if self.verbose:
            typer.echo("Extracting metadata...")
        metadata = extract_metadata(request.url)
        if self.verbose:
            typer.echo(f"  Title: {metadata.title}")
            typer.echo(f"  Channel: {metadata.channel}")
            duration = (
                seconds_to_display(metadata.duration_seconds)
                if metadata.duration_seconds
                else "unknown"
            )
            typer.echo(f"  Duration: {duration}")
            typer.echo(f"  Chapters: {len(metadata.chapters)} found")
            typer.echo(f"  Subtitles available: {metadata.subtitles_available}")

        workspace_id = metadata.video_id or _stable_workspace_id(metadata.url or request.url)
        ws = Workspace(request.workspace_base_dir, workspace_id)
        try:
            ws.discard_acquisition_artifacts()
            ws.save_metadata(metadata)

            subtitle_path: Path | None = None
            subtitle_source: str | None = None
            audio_path: Path | None = None
            video_path: Path | None = None
            if metadata.subtitles_available:
                if self.verbose:
                    typer.echo("Downloading subtitles...")
                try:
                    with tempfile.TemporaryDirectory() as tmp_dir:
                        sub_path, subtitle_source = extract_subtitles_with_source(
                            request.url,
                            self.config,
                            Path(tmp_dir),
                            metadata=metadata,
                        )
                        subtitle_path = ws.save_subtitles(sub_path)
                        ws.save_subtitle_source(subtitle_source)
                        if self.verbose:
                            typer.echo(f"  Saved: subtitles{sub_path.suffix}")
                except ExtractionError:
                    if self.verbose:
                        typer.echo("  Subtitle download failed, downloading media instead...")
                    audio_path, video_path = self._acquire_fallback_media(request, metadata, ws)
            else:
                audio_path, video_path = self._acquire_fallback_media(request, metadata, ws)

            return MediaAcquireResult(
                metadata=metadata,
                workspace=ws,
                audio_path=audio_path or ws.audio_path,
                subtitle_path=subtitle_path or ws.subtitle_path,
                subtitle_source=subtitle_source or ws.load_subtitle_source(),
                video_path=video_path,
            )
        except Exception as exc:
            raise MediaAcquisitionError(ws, exc) from exc

    def _acquire_fallback_media(
        self,
        request: MediaAcquireRequest,
        metadata,
        ws: Workspace,
    ) -> tuple[Path | None, Path | None]:
        if self._download_webpage_transcript(request.url, metadata, ws):
            return None, None
        if request.keep_video:
            return self._download_video_and_audio(request.url, metadata, ws)
        return self._download_audio(request.url, metadata, ws), None

    def _download_video_and_audio(
        self,
        url: str,
        metadata,
        ws: Workspace,
    ) -> tuple[Path, Path]:
        if self.verbose:
            typer.echo("Downloading video...")
        cookies_from = self.config.get("extract", {}).get("cookies_from")
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded_video = extract_video(
                url,
                Path(tmp_dir),
                video_id=metadata.video_id,
                cookies_from=cookies_from,
            )
            video_path = ws.save_video(downloaded_video)
        audio_path = extract_audio_from_video(video_path, ws.dir / "audio.mp3")
        return audio_path, video_path

    def _download_audio(self, url: str, metadata, ws: Workspace) -> Path:
        if self.verbose:
            typer.echo("Downloading audio...")
        cookies_from = self.config.get("extract", {}).get("cookies_from")
        with tempfile.TemporaryDirectory() as tmp_dir:
            audio_path = extract_audio(
                url,
                Path(tmp_dir),
                video_id=metadata.video_id,
                cookies_from=cookies_from,
            )
            saved = ws.save_audio(audio_path)
            if self.verbose:
                size_mb = saved.stat().st_size / 1e6
                typer.echo(f"  Saved: {saved.name} ({size_mb:.1f} MB)")

        if metadata.duration_seconds == 0:
            duration = get_duration(saved)
            metadata.duration_seconds = int(duration)
            ws.save_metadata(metadata)
            if self.verbose:
                typer.echo(
                    f"  Duration (from audio): {seconds_to_display(metadata.duration_seconds)}"
                )
        return saved

    def _download_webpage_transcript(self, url: str, metadata, ws: Workspace) -> bool:
        try:
            entries = extract_webpage_transcript(url, metadata)
        except Exception:
            return False

        if not entries:
            return False

        with tempfile.TemporaryDirectory() as tmp_dir:
            transcript_path = Path(tmp_dir) / f"{metadata.video_id or 'transcript'}.srt"
            write_transcript_srt(entries, transcript_path)
            saved = ws.save_subtitles(transcript_path)
            ws.save_subtitle_source("webpage_transcript")

        if self.verbose:
            typer.echo(f"  Found webpage transcript: {saved.name} ({len(entries)} entries)")
        return True


def _stable_workspace_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"media-{digest}"
