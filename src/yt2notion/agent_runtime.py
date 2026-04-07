"""Runtime helpers for file-backed CLI agent execution."""

from __future__ import annotations

import fcntl
import json
import os
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

import yaml

from yt2notion.config import AppConfig, load_config

DEFAULT_AGENT_HOME = Path("~/.yt2notion-agent").expanduser()


@dataclass(frozen=True)
class AgentConfig:
    """Minimal runtime agent configuration loaded from agent.yaml."""

    vault_path: str
    summaries_dir: str
    transcripts_dir: str
    workspace_dir: str
    codex_model: str
    reasoning_effort: str


@dataclass(frozen=True)
class AgentPaths:
    """Canonical file/directory paths under runtime agent home."""

    home: Path
    config_path: Path
    agents_path: Path
    queue_path: Path
    worker_path: Path
    jobs_dir: Path
    logs_dir: Path
    workspace_dir: Path


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _normalize_runtime_path(
    value: object,
    *,
    default: Path | None = None,
    anchor: Path | None = None,
    field_name: str = "path",
) -> str:
    if value is None:
        raw = ""
    elif isinstance(value, str):
        raw = value.strip()
    else:
        raise ValueError(f"{field_name} must be a string path")

    if not raw:
        if default is None:
            raise ValueError(f"{field_name} is required")
        raw = str(default)

    expanded = os.path.expandvars(os.path.expanduser(raw))
    candidate = Path(expanded)
    if not candidate.is_absolute():
        base = anchor if anchor is not None else Path.cwd()
        candidate = base / candidate
    normalized = str(candidate.resolve(strict=False))

    if not normalized:
        raise ValueError(f"{field_name} is required")
    return normalized


def _normalize_agent_config(
    agent_config: AgentConfig,
    runtime_default_workspace: Path,
    *,
    anchor: Path,
) -> AgentConfig:
    return AgentConfig(
        vault_path=_normalize_runtime_path(
            agent_config.vault_path,
            anchor=anchor,
            field_name="vault_path",
        ),
        summaries_dir=agent_config.summaries_dir,
        transcripts_dir=agent_config.transcripts_dir,
        workspace_dir=_normalize_runtime_path(
            agent_config.workspace_dir,
            default=runtime_default_workspace,
            anchor=anchor,
            field_name="workspace_dir",
        ),
        codex_model=agent_config.codex_model,
        reasoning_effort=agent_config.reasoning_effort,
    )


def default_runtime_agents_md() -> str:
    """Return runtime-only AGENTS.md content (separate from repo AGENTS.md)."""
    return "\n".join(
        [
            "# Runtime AGENTS.md",
            "",
            "- Codex is used only as a text-processing backend for media content.",
            "- summary mode only.",
            "- Obsidian writes are allowed only to the configured local vault.",
            "- No repository tasks, no code changes, no browsing, no autonomous agent behavior.",
            "- Always preserve source attribution in generated output.",
            "",
        ]
    )


def default_agent_yaml(home: Path) -> str:
    """Return starter agent.yaml content."""
    return "\n".join(
        [
            'vault_path: "/path/to/your/vault"',
            'summaries_dir: "yt2notion/summaries"',
            'transcripts_dir: "yt2notion/transcripts"',
            f'workspace_dir: "{home / "workspace"}"',
            'codex_model: "gpt-5.3-codex"',
            'reasoning_effort: "low"',
            "",
        ]
    )


def ensure_agent_home(home: Path | None = None) -> AgentPaths:
    """Create runtime directories/files if missing and return resolved paths."""
    runtime_home = (home or DEFAULT_AGENT_HOME).expanduser()
    runtime_home.mkdir(parents=True, exist_ok=True)

    jobs_dir = runtime_home / "jobs"
    logs_dir = runtime_home / "logs"
    workspace_dir = runtime_home / "workspace"
    jobs_dir.mkdir(exist_ok=True)
    logs_dir.mkdir(exist_ok=True)
    workspace_dir.mkdir(exist_ok=True)

    config_path = runtime_home / "agent.yaml"
    agents_path = runtime_home / "AGENTS.md"
    queue_path = runtime_home / "queue.json"
    worker_path = runtime_home / "worker.json"

    if not config_path.exists():
        config_path.write_text(default_agent_yaml(runtime_home), encoding="utf-8")
    if not agents_path.exists():
        agents_path.write_text(default_runtime_agents_md(), encoding="utf-8")
    if not queue_path.exists():
        queue_path.write_text(
            json.dumps(
                {"queued_job_ids": [], "updated_at": _now_iso()},
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    return AgentPaths(
        home=runtime_home,
        config_path=config_path,
        agents_path=agents_path,
        queue_path=queue_path,
        worker_path=worker_path,
        jobs_dir=jobs_dir,
        logs_dir=logs_dir,
        workspace_dir=workspace_dir,
    )


def load_agent_config(paths: AgentPaths) -> AgentConfig:
    """Load minimal runtime config from agent.yaml."""
    raw = yaml.safe_load(paths.config_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise ValueError("agent.yaml must contain a mapping/object at the top level")
    anchor = paths.config_path.parent
    return AgentConfig(
        vault_path=_normalize_runtime_path(
            raw.get("vault_path"),
            anchor=anchor,
            field_name="vault_path",
        ),
        summaries_dir=str(raw.get("summaries_dir", "yt2notion/summaries")),
        transcripts_dir=str(raw.get("transcripts_dir", "yt2notion/transcripts")),
        workspace_dir=_normalize_runtime_path(
            raw.get("workspace_dir"),
            default=paths.workspace_dir,
            anchor=anchor,
            field_name="workspace_dir",
        ),
        codex_model=str(raw.get("codex_model", "gpt-5.3-codex")),
        reasoning_effort=str(raw.get("reasoning_effort", "low")),
    )


def read_queue(paths: AgentPaths) -> dict[str, Any]:
    """Read queue.json."""
    with paths.queue_path.open(encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_SH)
        payload = json.load(handle)
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return payload


def write_queue(paths: AgentPaths, queue: dict[str, Any]) -> None:
    """Persist queue.json with updated timestamp."""
    payload = dict(queue)
    payload["updated_at"] = _now_iso()
    with paths.queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def write_job(paths: AgentPaths, record: dict[str, Any]) -> None:
    """Persist a job record under jobs/<job_id>.json."""
    job_path = paths.jobs_dir / f'{record["job_id"]}.json'
    paths.jobs_dir.mkdir(exist_ok=True)
    job_path.write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def build_runtime_app_config(
    base_config_path: str,
    agent_config: AgentConfig,
    agent_home: Path,
) -> AppConfig:
    """Build runtime AppConfig by layering agent overrides over repo config.yaml.

    AgentPaths.workspace_dir is the runtime-home default.
    AgentConfig.workspace_dir is the effective workspace for runtime AppConfig.
    """
    base = load_config(base_config_path)
    normalized_agent = _normalize_agent_config(
        agent_config,
        agent_home / "workspace",
        anchor=agent_home,
    )
    if not Path(normalized_agent.vault_path).is_dir():
        raise ValueError(
            f"agent.yaml vault_path must be an existing directory: {normalized_agent.vault_path}"
        )
    workspace_path = Path(normalized_agent.workspace_dir)
    if workspace_path.exists() and not workspace_path.is_dir():
        raise ValueError(
            "agent.yaml workspace_dir must be a directory path, "
            f"got file: {normalized_agent.workspace_dir}"
        )

    model = deepcopy(base.model)
    storage = deepcopy(base.storage)
    extract = deepcopy(base.extract)
    credit = deepcopy(base.credit)
    output = deepcopy(base.output)
    workspace = deepcopy(base.workspace)

    model["backend"] = "codex_cli"
    model["summarize_model"] = normalized_agent.codex_model
    model["translate_model"] = normalized_agent.codex_model
    model["review_model"] = normalized_agent.codex_model
    model["reasoning_effort"] = normalized_agent.reasoning_effort
    model["_runtime"] = {"codex_workdir": str(agent_home)}

    storage["backend"] = "obsidian"
    storage["obsidian"] = {
        "vault_path": normalized_agent.vault_path,
        "summaries_dir": normalized_agent.summaries_dir,
        "transcripts_dir": normalized_agent.transcripts_dir,
    }

    output["mode"] = "summary"
    workspace["base_dir"] = normalized_agent.workspace_dir

    return AppConfig(
        model=model,
        storage=storage,
        extract=extract,
        credit=credit,
        output=output,
        workspace=workspace,
    )
