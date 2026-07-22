"""CLI entry point for yt2notion."""

from __future__ import annotations

import json
import os
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from uuid import uuid4

import typer

from yt2notion.agent_runtime import (
    AgentPaths,
    ensure_agent_home,
    read_queue,
    write_job,
)
from yt2notion.agent_runtime import (
    load_agent_config as load_runtime_agent_config,
)
from yt2notion.agent_worker import (
    claim_worker_slot,
    enqueue_job,
    mark_stale_worker_failed,
    recover_orphaned_queued_jobs,
    retry_job,
    run_worker_once,
    spawn_background_worker,
    validate_job_id,
)
from yt2notion.application import create_yt2notion
from yt2notion.config import ConfigError, load_config
from yt2notion.extract import ExtractionError

app = typer.Typer(help="YouTube videos → structured Chinese notes → storage")
agent_app = typer.Typer(help="Manage local file-backed agent runtime")
RESUME_STEP_HELP = "Step to resume from (download/segment/transcribe/review/summarize)"
app.add_typer(agent_app, name="agent")
RECENT_JOB_OUTCOME_LIMIT = 5


@app.command()
def process(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    dry_run: bool = typer.Option(False, "--dry-run", help="Output result without publishing"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(None, "--from", help=RESUME_STEP_HELP),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary only"),
) -> None:
    """Process a video or podcast into a Chinese Notion page."""
    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    try:
        result = create_yt2notion(config, verbose=verbose).process(
            url,
            verbose=verbose,
            dry_run=dry_run,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
        if result and not dry_run:
            typer.echo(f"Done! {result}")
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None


@app.command()
def prepare(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    config_path: str = typer.Option("config.yaml", "--config", "-c", help="Config file path"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    resume: str = typer.Option(None, "--resume", help="Resume from workspace directory"),
    from_step: str = typer.Option(None, "--from", help=RESUME_STEP_HELP),
    workspace_dir: str = typer.Option(None, "--workspace-dir", help="Workspace base directory"),
    mode: str = typer.Option(None, "--mode", help="Output mode: summary only"),
) -> None:
    """Run processing without publishing and emit structured JSON for agent wrappers."""
    try:
        config = load_config(config_path)
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None

    try:
        prepared = create_yt2notion(config, verbose=verbose).prepare(
            url,
            verbose=verbose,
            resume_from=from_step,
            workspace_dir=resume or workspace_dir,
            mode=mode,
        )
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    payload = {
        "mode": "bundle",
        "is_long": prepared.is_long,
        "metadata": asdict(prepared.metadata),
        "workspace_dir": str(prepared.workspace.dir),
        "note_bundle": asdict(prepared.note_bundle),
    }
    typer.echo(json.dumps(payload, ensure_ascii=False, indent=2))


@app.command("transcribe")
def transcribe(
    url: str = typer.Argument(help="Media URL"),
    config_path: str | None = typer.Option(
        None,
        "--config",
        "-c",
        help=(
            "Config file path; defaults to ~/.yt2notion/config.yaml, "
            "agent config, then ./config.yaml"
        ),
    ),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Verbose output"),
    workspace_dir: str | None = typer.Option(None, "--workspace-dir", help="Workspace base dir"),
    keep_video: bool = typer.Option(
        True,
        "--keep-video/--no-video",
        help="Keep the downloaded video artifact in the workspace",
    ),
    json_output: bool = typer.Option(False, "--json", help="Emit JSON result summary"),
) -> None:
    """Download media, extract audio, transcribe via ASR, and write local artifacts."""
    from yt2notion.audio import AudioError
    from yt2notion.media_transcribe import (
        resolve_media_transcribe_config_path,
        transcribe_media,
        write_result_json,
    )

    try:
        resolved_config_path = resolve_media_transcribe_config_path(config_path)
        config = load_config(str(resolved_config_path))
        result = transcribe_media(
            url,
            config,
            workspace_dir=workspace_dir,
            keep_video=keep_video,
            verbose=verbose,
        )
    except ConfigError as e:
        typer.echo(f"Configuration error: {e}", err=True)
        raise typer.Exit(1) from None
    except ExtractionError as e:
        typer.echo(f"Extraction error: {e}", err=True)
        raise typer.Exit(1) from None
    except AudioError as e:
        typer.echo(f"Audio error: {e}", err=True)
        raise typer.Exit(1) from None
    except Exception as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1) from None

    if json_output:
        typer.echo(write_result_json(result))
        return

    typer.echo(f"Workspace: {result.workspace.dir}")
    if result.video_path:
        typer.echo(f"Video: {result.video_path}")
    typer.echo(f"Audio: {result.audio_path}")
    typer.echo(f"Transcript JSON: {result.transcripts_path}")
    typer.echo(f"Transcript Markdown: {result.transcript_markdown_path}")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _build_queued_job_record(url: str) -> dict:
    job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid4().hex[:6]}"
    return {
        "job_id": job_id,
        "url": url,
        "status": "queued",
        "created_at": _now_iso(),
        "updated_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "current_step": None,
        "completed_steps": [],
        "workspace_dir": None,
        "video_id": None,
        "title": None,
        "channel": None,
        "result_path": None,
        "error": None,
        "asr_fallback_used": False,
    }


def _ensure_home(agent_home: str | None) -> Path | None:
    if agent_home:
        return Path(agent_home).expanduser()
    env_home = os.environ.get("YT2NOTION_AGENT_HOME")
    if env_home:
        return Path(env_home).expanduser()
    return None


def _job_record_path(paths, job_id: str) -> Path:
    return paths.jobs_dir / f"{validate_job_id(job_id)}.json"


def _read_job_record(paths, job_id: str) -> dict:
    return json.loads(_job_record_path(paths, job_id).read_text(encoding="utf-8"))


def _list_job_records(paths) -> list[dict]:
    jobs: list[dict] = []
    for job_path in paths.jobs_dir.glob("*.json"):
        try:
            jobs.append(json.loads(job_path.read_text(encoding="utf-8")))
        except json.JSONDecodeError:
            continue
    return sorted(jobs, key=lambda item: item.get("updated_at") or "", reverse=True)


def _recent_job_outcomes(paths, *, limit: int = RECENT_JOB_OUTCOME_LIMIT) -> list[dict]:
    outcomes: list[dict] = []
    for record in _list_job_records(paths):
        status = record.get("status")
        if status not in {"completed", "failed"}:
            continue
        outcomes.append(
            {
                "job_id": record.get("job_id"),
                "status": status,
                "finished_at": record.get("finished_at"),
                "result_path": record.get("result_path"),
                "error": record.get("error"),
            }
        )
        if len(outcomes) >= limit:
            break
    return outcomes


def _render_status_output(
    *,
    worker_state: str,
    active_job_id: str | None,
    active_step: str | None,
    queued_jobs: int,
    recent_outcomes: list[dict],
) -> str:
    lines = [
        f"Worker: {worker_state}",
        f"Active Job: {active_job_id or '-'}",
        f"Active Step: {active_step or '-'}",
        f"Queued Jobs: {queued_jobs}",
        "Recent Outcomes:",
    ]
    if not recent_outcomes:
        lines.append("-")
    else:
        for outcome in recent_outcomes:
            detail = outcome.get("result_path") or outcome.get("error") or "-"
            lines.append(
                "\t".join(
                    [
                        str(outcome.get("job_id") or "-"),
                        str(outcome.get("status") or "-"),
                        str(outcome.get("finished_at") or "-"),
                        str(detail),
                    ]
                )
            )
    return "\n".join(lines)


def _render_list_output(rows: list[dict]) -> str:
    lines = ["job_id\tstatus\ttitle_or_url\tcurrent_step_or_result\tupdated_at"]
    for row in rows:
        current_or_result = row.get("current_step") or row.get("result_path") or "-"
        lines.append(
            "\t".join(
                [
                    str(row.get("job_id") or "-"),
                    str(row.get("status") or "-"),
                    str(row.get("title_or_url") or "-"),
                    str(current_or_result),
                    str(row.get("updated_at") or "-"),
                ]
            )
        )
    return "\n".join(lines)


def _validate_agent_config_path(config_path: str) -> str:
    resolved = Path(config_path).expanduser().resolve()
    if not resolved.exists() or not resolved.is_file():
        typer.echo(f"Configuration error: Config file not found: {resolved}", err=True)
        raise typer.Exit(1) from None
    try:
        load_config(str(resolved))
    except ConfigError as exc:
        typer.echo(f"Configuration error: {exc}", err=True)
        raise typer.Exit(1) from None
    return str(resolved)


def _resolve_agent_base_config_path(paths: AgentPaths, config_path: str | None) -> str:
    if config_path is not None:
        candidate = Path(config_path).expanduser()
        if config_path == "config.yaml" and not candidate.exists():
            return str(paths.runtime_config_path)
        return config_path
    return str(paths.runtime_config_path)


def _start_worker_if_idle(paths, *, config_path: str) -> bool:
    recover_orphaned_queued_jobs(paths)
    queue = read_queue(paths)
    queued_job_ids = queue.get("queued_job_ids", [])
    if not queued_job_ids:
        return False
    if paths.worker_path.exists():
        return False
    if not claim_worker_slot(
        paths,
        pid=os.getpid(),
        job_id=str(queued_job_ids[0]),
        mode="spawning",
    ):
        return False
    try:
        spawn_background_worker(paths, base_config_path=config_path)
    except Exception:
        paths.worker_path.unlink(missing_ok=True)
        raise
    return True


def _drain_queue(paths, *, config_path: str, capture_pipeline_output: bool) -> None:
    agent_config = load_runtime_agent_config(paths)
    while run_worker_once(
        paths,
        agent_config,
        base_config_path=config_path,
        capture_pipeline_output=capture_pipeline_output,
    ):
        continue


@agent_app.command("init")
def agent_init(
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
) -> None:
    """Initialize runtime files and directories."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    typer.echo(str(paths.home))


@agent_app.command("add")
def agent_add(
    url: str = typer.Argument(help="YouTube or podcast URL"),
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Enqueue a new agent job and start worker if idle."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    resolved_config_path = _validate_agent_config_path(
        _resolve_agent_base_config_path(paths, config_path)
    )
    record = _build_queued_job_record(url)
    write_job(paths, record)
    enqueue_job(paths, record["job_id"])

    worker_started = _start_worker_if_idle(paths, config_path=resolved_config_path)
    worker_label = "worker started" if worker_started else "worker already running"
    typer.echo(f"Queued {record['job_id']} ({worker_label})")


@agent_app.command("status")
def agent_status(
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
) -> None:
    """Show queue and worker summary."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    queue = read_queue(paths)
    active_job_id: str | None = None
    active_step: str | None = None
    if paths.worker_path.exists():
        worker_payload = json.loads(paths.worker_path.read_text(encoding="utf-8"))
        active_job_id_raw = worker_payload.get("job_id")
        if isinstance(active_job_id_raw, str) and active_job_id_raw:
            active_job_id = active_job_id_raw
            job_path = _job_record_path(paths, active_job_id)
            if job_path.exists():
                active_step = _read_job_record(paths, active_job_id).get("current_step")

    payload = {
        "worker_state": "running" if paths.worker_path.exists() else "idle",
        "active_job_id": active_job_id,
        "active_step": active_step,
        "queued_jobs": len(queue.get("queued_job_ids", [])),
        "recent_outcomes": _recent_job_outcomes(paths),
    }
    typer.echo(_render_status_output(**payload))


@agent_app.command("list")
def agent_list(
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
) -> None:
    """List jobs ordered by updated_at desc."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    rows = []
    for record in _list_job_records(paths):
        rows.append(
            {
                "job_id": record.get("job_id"),
                "status": record.get("status"),
                "title_or_url": record.get("title") or record.get("url"),
                "current_step": record.get("current_step"),
                "result_path": record.get("result_path"),
                "updated_at": record.get("updated_at"),
            }
        )
    typer.echo(_render_list_output(rows))


@agent_app.command("show")
def agent_show(
    job_id: str = typer.Argument(help="Job id"),
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
) -> None:
    """Show full state for one job."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    try:
        job_path = _job_record_path(paths, job_id)
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    if not job_path.exists():
        typer.echo(f"Job not found: {job_id}", err=True)
        raise typer.Exit(1) from None
    typer.echo(job_path.read_text(encoding="utf-8"))


@agent_app.command("logs")
def agent_logs(
    job_id: str = typer.Argument(help="Job id"),
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
) -> None:
    """Print job log text."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    try:
        log_path = paths.logs_dir / f"{validate_job_id(job_id)}.log"
    except ValueError as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    if not log_path.exists():
        typer.echo(f"Log not found for job: {job_id}", err=True)
        raise typer.Exit(1) from None
    typer.echo(log_path.read_text(encoding="utf-8"), nl=False)


@agent_app.command("retry")
def agent_retry(
    job_id: str = typer.Argument(help="Failed job id"),
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Retry a failed job and start worker if idle."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    resolved_config_path = _validate_agent_config_path(
        _resolve_agent_base_config_path(paths, config_path)
    )
    try:
        new_job_id = retry_job(paths, job_id)
    except (FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1) from None
    worker_started = _start_worker_if_idle(paths, config_path=resolved_config_path)
    worker_label = "worker started" if worker_started else "worker already running"
    typer.echo(f"Queued retry {new_job_id} for {job_id} ({worker_label})")


@agent_app.command("run")
def agent_run(
    foreground: bool = typer.Option(False, "--foreground", help="Run worker in foreground"),
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Run worker in foreground or spawn a background worker."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    queue = read_queue(paths)
    queued_job_ids = queue.get("queued_job_ids", [])
    if foreground:
        if paths.worker_path.exists():
            typer.echo("Error: worker already running", err=True)
            raise typer.Exit(1) from None
        if not queued_job_ids:
            typer.echo("queue empty")
            return
        resolved_config_path = _validate_agent_config_path(
            _resolve_agent_base_config_path(paths, config_path)
        )
        if not claim_worker_slot(
            paths,
            pid=os.getpid(),
            job_id=str(queued_job_ids[0]),
            mode="foreground",
        ):
            typer.echo("Error: worker already running", err=True)
            raise typer.Exit(1) from None
        _drain_queue(paths, config_path=resolved_config_path, capture_pipeline_output=False)
        return

    if not queued_job_ids:
        typer.echo("queue empty")
        return
    resolved_config_path = _validate_agent_config_path(
        _resolve_agent_base_config_path(paths, config_path)
    )
    if _start_worker_if_idle(paths, config_path=resolved_config_path):
        typer.echo("worker started")
        return
    typer.echo("worker already running")


@agent_app.command("_worker", hidden=True)
def agent_worker_entrypoint(
    agent_home: str = typer.Option(None, "--agent-home", help="Agent runtime directory"),
    config_path: str | None = typer.Option(None, "--config", "-c", help="Config file path"),
) -> None:
    """Hidden entrypoint for background worker process."""
    paths = ensure_agent_home(_ensure_home(agent_home))
    mark_stale_worker_failed(paths)
    recover_orphaned_queued_jobs(paths)
    resolved_config_path = _validate_agent_config_path(
        _resolve_agent_base_config_path(paths, config_path)
    )
    queue = read_queue(paths)
    queued_job_ids = queue.get("queued_job_ids", [])
    if not queued_job_ids:
        return
    if not paths.worker_path.exists() and not claim_worker_slot(
        paths,
        pid=os.getpid(),
        job_id=str(queued_job_ids[0]),
        mode="background",
    ):
        raise typer.Exit(1) from None
    _drain_queue(paths, config_path=resolved_config_path, capture_pipeline_output=True)


if __name__ == "__main__":
    app()
