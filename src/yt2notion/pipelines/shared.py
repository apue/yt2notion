"""Small helpers genuinely shared by multiple product pipelines."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yt2notion.config import AppConfig


def workspace_base(config: AppConfig, workspace_dir: str | None) -> Path:
    """Resolve the configured workspace root without creating it."""
    configured = workspace_dir or config.workspace.get("base_dir", "./workspace")
    return Path(configured).expanduser()
