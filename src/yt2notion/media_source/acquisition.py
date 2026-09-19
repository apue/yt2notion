"""Pure acquisition planning and plan execution."""

from __future__ import annotations

import hashlib
from pathlib import Path

from yt2notion.media_source.base import (
    AcquiredMedia,
    AcquisitionError,
    SourceOperation,
    SourceOperationError,
    SourceProbe,
    SourceProvider,
)
from yt2notion.runtime import provider_call
from yt2notion.workspace import Workspace


def plan_acquisition(probe: SourceProbe, *, keep_video: bool) -> tuple[SourceOperation, ...]:
    """Create deterministic subtitle/webpage/media fallback policy."""
    operations: list[SourceOperation] = []
    if probe.subtitles_available:
        operations.append("subtitle")
    operations.append("webpage_transcript")
    operations.append("video" if keep_video else "audio")
    return tuple(operations)


def acquire_media(
    provider: SourceProvider,
    *,
    url: str,
    workspace_base_dir: Path,
    keep_video: bool = False,
) -> AcquiredMedia:
    """Own workspace lifecycle and execute the acquisition fallback policy."""
    if not url.strip():
        raise ValueError("source locator must not be empty")
    with provider_call("source.probe"):
        probe = provider.probe(url)
    workspace_id = probe.metadata.video_id or _stable_workspace_id(probe.metadata.url or url)
    workspace = Workspace(workspace_base_dir, workspace_id)
    try:
        workspace.discard_acquisition_artifacts()
        workspace.save_metadata(probe.metadata)
        plan = plan_acquisition(probe, keep_video=keep_video)
        unavailable: SourceOperationError | None = None
        for operation in plan:
            try:
                with provider_call(f"source.{operation}"):
                    result = provider.execute(operation, probe, workspace)
            except SourceOperationError as exc:
                if exc.category != "unavailable":
                    raise
                unavailable = exc
                continue
            return AcquiredMedia(
                metadata=probe.metadata,
                workspace=workspace,
                audio_path=result.audio_path or workspace.audio_path,
                subtitle_path=result.subtitle_path or workspace.subtitle_path,
                subtitle_source=result.subtitle_source or workspace.load_subtitle_source(),
                video_path=result.video_path,
            )
        if unavailable is not None:
            raise unavailable
        raise SourceOperationError("plan", "provider", "acquisition plan produced no artifact")
    except Exception as exc:
        raise AcquisitionError(workspace, exc) from exc


def _stable_workspace_id(value: str) -> str:
    digest = hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]
    return f"media-{digest}"
