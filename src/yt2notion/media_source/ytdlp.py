"""yt-dlp source-provider adapter."""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

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
    OperationResult,
    SourceFailureCategory,
    SourceOperation,
    SourceOperationError,
    SourceProbe,
    SourceRef,
)
from yt2notion.process import seconds_to_display

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace


class YtDlpSourceProvider:
    """Run explicit yt-dlp operations behind normalized provider failures."""

    def __init__(self, config: dict, *, verbose: bool = False) -> None:
        self._config = config
        self._verbose = verbose

    def probe(self, source: SourceRef) -> SourceProbe:
        """Fetch metadata and subtitle capability information once."""
        try:
            if self._verbose:
                typer.echo("Extracting metadata...")
            metadata = extract_metadata(source.locator)
        except Exception as exc:
            raise _normalize_failure("probe", exc) from exc
        if self._verbose:
            duration = (
                seconds_to_display(metadata.duration_seconds)
                if metadata.duration_seconds
                else "unknown"
            )
            typer.echo(f"  Title: {metadata.title}")
            typer.echo(f"  Channel: {metadata.channel}")
            typer.echo(f"  Duration: {duration}")
            typer.echo(f"  Chapters: {len(metadata.chapters)} found")
            typer.echo(f"  Subtitles available: {metadata.subtitles_available}")
        return SourceProbe(source=source, metadata=metadata)

    def execute(
        self,
        operation: SourceOperation,
        probe: SourceProbe,
        workspace: Workspace,
    ) -> OperationResult:
        """Execute one planned provider operation and persist its local artifacts."""
        try:
            if operation == "subtitle":
                return self._subtitle(probe, workspace)
            if operation == "webpage_transcript":
                return self._webpage_transcript(probe, workspace)
            if operation == "audio":
                return self._audio(probe, workspace)
            if operation == "video":
                return self._video(probe, workspace)
        except SourceOperationError:
            raise
        except Exception as exc:
            raise _normalize_failure(operation, exc) from exc
        raise SourceOperationError(operation, "provider", f"unknown operation: {operation}")

    def _subtitle(self, probe: SourceProbe, workspace: Workspace) -> OperationResult:
        if not probe.subtitles_available:
            raise SourceOperationError("subtitle", "unavailable", "subtitles unavailable")
        if self._verbose:
            typer.echo("Downloading subtitles...")
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded, source = extract_subtitles_with_source(
                probe.source.locator,
                self._config,
                Path(tmp_dir),
                metadata=probe.metadata,
            )
            subtitle_path = workspace.save_subtitles(downloaded)
        workspace.save_subtitle_source(source)
        return OperationResult(
            subtitle_path=subtitle_path,
            subtitle_source=source,
        )

    def _webpage_transcript(
        self,
        probe: SourceProbe,
        workspace: Workspace,
    ) -> OperationResult:
        entries = extract_webpage_transcript(
            probe.metadata.url or probe.source.locator,
            probe.metadata,
        )
        if not entries:
            raise SourceOperationError(
                "webpage_transcript",
                "unavailable",
                "webpage transcript unavailable",
            )
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded = write_transcript_srt(
                entries,
                Path(tmp_dir) / f"{probe.metadata.video_id or 'transcript'}.srt",
            )
            subtitle_path = workspace.save_subtitles(downloaded)
        workspace.save_subtitle_source("webpage_transcript")
        return OperationResult(
            subtitle_path=subtitle_path,
            subtitle_source="webpage_transcript",
        )

    def _audio(self, probe: SourceProbe, workspace: Workspace) -> OperationResult:
        if self._verbose:
            typer.echo("Downloading audio...")
        extract_cfg = self._config.get("extract", {})
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded = extract_audio(
                probe.metadata.url or probe.source.locator,
                Path(tmp_dir),
                video_id=probe.metadata.video_id,
                cookies_from=extract_cfg.get("cookies_from"),
            )
            audio_path = workspace.save_audio(downloaded)
        self._save_duration(probe.metadata, audio_path, workspace)
        return OperationResult(audio_path=audio_path)

    def _video(self, probe: SourceProbe, workspace: Workspace) -> OperationResult:
        if self._verbose:
            typer.echo("Downloading video...")
        extract_cfg = self._config.get("extract", {})
        with tempfile.TemporaryDirectory() as tmp_dir:
            downloaded = extract_video(
                probe.metadata.url or probe.source.locator,
                Path(tmp_dir),
                video_id=probe.metadata.video_id,
                cookies_from=extract_cfg.get("cookies_from"),
            )
            video_path = workspace.save_video(downloaded)
        audio_path = extract_audio_from_video(video_path, workspace.dir / "audio.mp3")
        self._save_duration(probe.metadata, audio_path, workspace)
        return OperationResult(audio_path=audio_path, video_path=video_path)

    @staticmethod
    def _save_duration(metadata: VideoMeta, audio_path: Path, workspace: Workspace) -> None:
        if metadata.duration_seconds == 0:
            metadata.duration_seconds = int(get_duration(audio_path))
            workspace.save_metadata(metadata)


def _normalize_failure(operation: str, exc: Exception) -> SourceOperationError:
    message = str(exc).lower()
    category: SourceFailureCategory
    if any(token in message for token in ("sign in", "login", "authentication", "cookies")):
        category = "authentication"
    elif isinstance(exc, (FileNotFoundError, PermissionError)) or any(
        token in message
        for token in (
            "yt-dlp not found",
            "not found in path",
            "no such file",
            "permission denied",
        )
    ):
        category = "local_resource"
    elif isinstance(exc, TimeoutError) or "timed out" in message:
        category = "transient"
    elif operation == "subtitle" and isinstance(exc, ExtractionError):
        category = "unavailable"
    else:
        category = "provider"
    return SourceOperationError(operation, category, exc)


# Backwards name intentionally omitted: callers depend on SourceProvider, not this adapter.
