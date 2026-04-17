"""Worker helpers for file-backed CLI agent jobs."""

from __future__ import annotations

import fcntl
import json
import os
import re
import subprocess
import sys
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from yt2notion.agent_runtime import (
    AgentConfig,
    AgentPaths,
    build_runtime_app_config,
    read_queue,
    write_job,
)
from yt2notion.pipeline import run_pipeline

_JOB_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_SPAWNING_GRACE_SECONDS = 10


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def validate_job_id(job_id: str) -> str:
    if not _JOB_ID_PATTERN.fullmatch(job_id):
        raise ValueError(f"Invalid job id: {job_id}")
    return job_id


def _read_job(paths: AgentPaths, job_id: str) -> dict:
    normalized_job_id = validate_job_id(job_id)
    return json.loads((paths.jobs_dir / f"{normalized_job_id}.json").read_text(encoding="utf-8"))


def _job_log_path(paths: AgentPaths, job_id: str) -> Path:
    return paths.logs_dir / f"{validate_job_id(job_id)}.log"


def append_job_log(paths: AgentPaths, job_id: str, line: str) -> None:
    with _job_log_path(paths, job_id).open("a", encoding="utf-8") as handle:
        handle.write(f"{_now_iso()} {line}\n")


def _classify_failure_summary(
    error: str,
    *,
    current_step: str | None,
) -> tuple[str, str, str, str]:
    text = error.lower()
    step = current_step or "unknown"

    if "http error 403" in text:
        return ("download", "audio_download", "source_forbidden", "limited")
    if "unexpected_eof_while_reading" in text or "ssl: unexpected_eof_while_reading" in text:
        return ("download", "metadata", "ssl_eof", "safe")
    if "yt-dlp not found" in text:
        return ("download", "tooling", "missing_ytdlp", "no")
    if "no subtitles and no asr endpoint configured" in text:
        return ("transcribe", "asr_config", "missing_asr_endpoint", "no")
    if "asr request failed" in text:
        return ("transcribe", "asr_request", "asr_request_failed", "limited")
    if "failed after 3 attempts" in text and "command '['codex'" in text:
        return (step, "codex_exec", "codex_exec_failed", "limited")
    if "codex" in text and (
        "profile" in text
        or "config" in text
        or "reasoning_effort" in text
        or "model" in text
    ):
        return (step, "codex_config", "codex_config_invalid", "no")
    return (step, "-", "unknown", "unknown")


def _append_failure_summary(
    paths: AgentPaths,
    job_id: str,
    *,
    current_step: str | None,
    error: str,
) -> None:
    step, substep, hint, retry = _classify_failure_summary(error, current_step=current_step)
    append_job_log(paths, job_id, "=== FAILURE SUMMARY ===")
    append_job_log(paths, job_id, f"step: {step}")
    append_job_log(paths, job_id, f"substep: {substep}")
    append_job_log(paths, job_id, f"hint: {hint}")
    append_job_log(paths, job_id, f"retry: {retry}")
    append_job_log(paths, job_id, "=== END FAILURE SUMMARY ===")


class _TeeStream:
    def __init__(self, *targets) -> None:
        self._targets = targets

    def write(self, data: str) -> int:
        for target in self._targets:
            target.write(data)
        return len(data)

    def flush(self) -> None:
        for target in self._targets:
            target.flush()


def _notification_line(job_id: str, status: str, detail: str) -> str:
    return f"JOB {job_id} {status} {detail}"


def _emit_notification(paths: AgentPaths, job_id: str, notification: str) -> None:
    append_job_log(paths, job_id, notification)
    print(notification)


def _resolve_job_metadata_path(
    paths: AgentPaths,
    agent_config: AgentConfig,
    job_id: str,
) -> tuple[Path, dict] | None:
    current = _read_job(paths, job_id)
    current_workspace_dir = current.get("workspace_dir")
    if isinstance(current_workspace_dir, str) and current_workspace_dir:
        metadata_path = Path(current_workspace_dir) / "metadata.json"
        if metadata_path.exists():
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            return metadata_path, metadata

    workspace_root = Path(agent_config.workspace_dir)
    job_url = current.get("url")
    for metadata_path in sorted(
        workspace_root.glob("*/metadata.json"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    ):
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        if metadata.get("url") == job_url:
            return metadata_path, metadata
    return None


def _backfill_job_metadata(paths: AgentPaths, agent_config: AgentConfig, job_id: str) -> None:
    resolved = _resolve_job_metadata_path(paths, agent_config, job_id)
    if resolved is None:
        return

    metadata_path, metadata = resolved
    current = _read_job(paths, job_id)
    current["workspace_dir"] = str(metadata_path.parent)
    current["video_id"] = metadata.get("video_id")
    current["title"] = metadata.get("title")
    current["channel"] = metadata.get("channel")
    current["updated_at"] = _now_iso()
    write_job(paths, current)


def _persist_asr_fallback_used(paths: AgentPaths, job_id: str) -> None:
    current = _read_job(paths, job_id)
    workspace_dir = current.get("workspace_dir")
    used = False
    if isinstance(workspace_dir, str) and workspace_dir:
        workspace_path = Path(workspace_dir)
        if workspace_path.exists():
            from yt2notion.workspace import Workspace

            workspace = Workspace(workspace_path.parent, workspace_path.name)
            used = workspace.asr_fallback_used()
    current["asr_fallback_used"] = used
    current["updated_at"] = _now_iso()
    write_job(paths, current)


def _backfill_job_metadata_if_workspace_known(
    paths: AgentPaths,
    agent_config: AgentConfig,
    job_id: str,
) -> None:
    current = _read_job(paths, job_id)
    workspace_dir = current.get("workspace_dir")
    if not isinstance(workspace_dir, str) or not workspace_dir:
        return
    _backfill_job_metadata(paths, agent_config, job_id)


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _spawning_grace_active(worker: dict) -> bool:
    if worker.get("mode") != "spawning":
        return False
    try:
        pid = int(worker.get("pid", 0))
    except (TypeError, ValueError):
        return False
    if pid and not _pid_alive(pid):
        # Parent CLI crashed between claim and spawn — don't wait for grace.
        return False
    started_at = worker.get("started_at")
    if not isinstance(started_at, str) or not started_at:
        return False
    try:
        started = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    return (datetime.now().astimezone() - started).total_seconds() < _SPAWNING_GRACE_SECONDS


def _read_worker_state(paths: AgentPaths) -> dict | None:
    if not paths.worker_path.exists():
        return None
    try:
        return json.loads(paths.worker_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        paths.worker_path.unlink(missing_ok=True)
        return None


def _write_worker_state(
    paths: AgentPaths,
    *,
    pid: int,
    job_id: str | None,
    mode: str,
    exclusive: bool = False,
) -> bool:
    payload = json.dumps(
        {
            "pid": pid,
            "job_id": job_id,
            "started_at": _now_iso(),
            "mode": mode,
        },
        ensure_ascii=False,
        indent=2,
    )
    if exclusive:
        try:
            fd = os.open(paths.worker_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
        except FileExistsError:
            return False
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(payload)
        return True

    temp_path = paths.worker_path.with_suffix(".json.tmp")
    temp_path.write_text(payload, encoding="utf-8")
    temp_path.replace(paths.worker_path)
    return True


def claim_worker_slot(paths: AgentPaths, *, pid: int, job_id: str | None, mode: str) -> bool:
    normalized_job_id = validate_job_id(job_id) if job_id is not None else None
    return _write_worker_state(
        paths,
        pid=pid,
        job_id=normalized_job_id,
        mode=mode,
        exclusive=True,
    )


def enqueue_job(paths: AgentPaths, job_id: str) -> None:
    normalized_job_id = validate_job_id(job_id)
    with paths.queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        payload = json.load(handle)
        queued_job_ids = payload.setdefault("queued_job_ids", [])
        queued_job_ids.append(normalized_job_id)
        payload["updated_at"] = _now_iso()
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def dequeue_job(paths: AgentPaths) -> str | None:
    with paths.queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        payload = json.load(handle)
        queued_job_ids = payload.setdefault("queued_job_ids", [])
        job_id = queued_job_ids.pop(0) if queued_job_ids else None
        payload["updated_at"] = _now_iso()
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
    return str(job_id) if job_id is not None else None


def peek_queue_job(paths: AgentPaths) -> str | None:
    queue = read_queue(paths)
    queued_job_ids = queue.get("queued_job_ids", [])
    if not queued_job_ids:
        return None
    return str(queued_job_ids[0])


def remove_queued_job(paths: AgentPaths, job_id: str) -> None:
    normalized_job_id = validate_job_id(job_id)
    with paths.queue_path.open("r+", encoding="utf-8") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        payload = json.load(handle)
        queued_job_ids = payload.setdefault("queued_job_ids", [])
        payload["queued_job_ids"] = [
            queued_job_id for queued_job_id in queued_job_ids if queued_job_id != normalized_job_id
        ]
        payload["updated_at"] = _now_iso()
        handle.seek(0)
        handle.truncate()
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.flush()
        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def recover_orphaned_queued_jobs(paths: AgentPaths) -> None:
    queue = read_queue(paths)
    queued_job_ids = {
        validate_job_id(str(job_id))
        for job_id in queue.get("queued_job_ids", [])
        if isinstance(job_id, str)
    }
    worker = _read_worker_state(paths) or {}
    active_job_id = worker.get("job_id")
    for job_path in sorted(paths.jobs_dir.glob("*.json")):
        try:
            record = json.loads(job_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        job_id = record.get("job_id")
        if not isinstance(job_id, str):
            continue
        try:
            normalized_job_id = validate_job_id(job_id)
        except ValueError:
            continue
        if record.get("status") != "queued":
            continue
        if normalized_job_id in queued_job_ids or normalized_job_id == active_job_id:
            continue
        enqueue_job(paths, normalized_job_id)
        queued_job_ids.add(normalized_job_id)


def mark_stale_worker_failed(paths: AgentPaths) -> None:
    worker = _read_worker_state(paths)
    if worker is None:
        return
    if _spawning_grace_active(worker):
        return
    try:
        pid = int(worker.get("pid", 0))
    except (TypeError, ValueError):
        paths.worker_path.unlink(missing_ok=True)
        return
    if pid and _pid_alive(pid):
        return

    job_id = worker.get("job_id")
    if isinstance(job_id, str) and job_id:
        try:
            record = _read_job(paths, job_id)
        except (FileNotFoundError, ValueError, json.JSONDecodeError):
            paths.worker_path.unlink(missing_ok=True)
            return
        queue = read_queue(paths)
        queued_job_ids = queue.get("queued_job_ids", [])
        if record.get("status") in {"starting", "running"}:
            record["status"] = "failed"
            record["current_step"] = None
            record["error"] = "worker process exited before job completion"
            record["finished_at"] = _now_iso()
            record["updated_at"] = _now_iso()
            write_job(paths, record)
            remove_queued_job(paths, str(job_id))
            append_job_log(paths, str(job_id), "FAILED worker process exited before job completion")
        elif record.get("status") == "queued" and str(job_id) not in queued_job_ids:
            enqueue_job(paths, str(job_id))
            append_job_log(paths, str(job_id), "REQUEUED after worker exited before start")

    paths.worker_path.unlink(missing_ok=True)


def retry_job(paths: AgentPaths, job_id: str) -> str:
    original = _read_job(paths, job_id)
    if original.get("status") != "failed":
        raise ValueError("Only failed jobs can be retried")

    new_job_id = f"{datetime.now().strftime('%Y%m%d-%H%M%S')}-retry-{uuid4().hex[:6]}"
    new_record = {
        "job_id": new_job_id,
        "url": original["url"],
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
    write_job(paths, new_record)
    enqueue_job(paths, new_job_id)
    append_job_log(paths, new_job_id, f"QUEUED retry for {job_id}")
    return new_job_id


def run_worker_once(
    paths: AgentPaths,
    agent_config: AgentConfig,
    *,
    base_config_path: str,
    capture_pipeline_output: bool = False,
) -> bool:
    job_id = peek_queue_job(paths)
    if job_id is None:
        paths.worker_path.unlink(missing_ok=True)
        return False
    _write_worker_state(
        paths,
        pid=os.getpid(),
        job_id=job_id,
        mode="background" if capture_pipeline_output else "foreground",
    )

    record = _read_job(paths, job_id)
    record["status"] = "starting"
    record["started_at"] = _now_iso()
    record["updated_at"] = _now_iso()
    write_job(paths, record)
    append_job_log(paths, job_id, "STARTED")
    remove_queued_job(paths, job_id)

    def on_progress(step: str, event: str, message: str | None = None) -> None:
        current = _read_job(paths, job_id)
        current["updated_at"] = _now_iso()
        if event == "started":
            current["status"] = "running"
            current["current_step"] = step
        elif event == "completed":
            completed = current.get("completed_steps") or []
            current["completed_steps"] = list(dict.fromkeys([*completed, step]))
            if current.get("current_step") == step:
                current["current_step"] = None
        elif event == "skipped":
            if current.get("current_step") == step:
                current["current_step"] = None
        elif event == "failed":
            current["status"] = "failed"
            current["current_step"] = step
            if message:
                current["error"] = message
        write_job(paths, current)
        append_job_log(paths, job_id, f"{step}:{event} {message or ''}".strip())
        if step == "download" and event == "completed":
            _backfill_job_metadata(paths, agent_config, job_id)

    try:
        app_config = build_runtime_app_config(base_config_path, agent_config, paths.home)
        with ExitStack() as stack:
            log_handle = stack.enter_context(
                _job_log_path(paths, job_id).open("a", encoding="utf-8")
            )
            if capture_pipeline_output:
                stack.enter_context(redirect_stdout(log_handle))
                stack.enter_context(redirect_stderr(log_handle))
            else:
                stack.enter_context(redirect_stdout(_TeeStream(sys.stdout, log_handle)))
                stack.enter_context(redirect_stderr(_TeeStream(sys.stderr, log_handle)))
            result_path = run_pipeline(
                record["url"],
                app_config,
                verbose=True,
                mode="summary",
                progress_callback=on_progress,
            )
    except Exception as exc:
        failed = _read_job(paths, job_id)
        failure_error = str(exc)
        failure_step = failed.get("current_step")
        failed["status"] = "failed"
        failed["current_step"] = None
        failed["error"] = failure_error
        failed["finished_at"] = _now_iso()
        failed["updated_at"] = _now_iso()
        write_job(paths, failed)
        _backfill_job_metadata_if_workspace_known(paths, agent_config, job_id)
        _persist_asr_fallback_used(paths, job_id)
        notification = _notification_line(job_id, "FAILED", failure_error)
        _emit_notification(paths, job_id, notification)
        _append_failure_summary(
            paths,
            job_id,
            current_step=failure_step if isinstance(failure_step, str) else None,
            error=failure_error,
        )
        return True

    completed = _read_job(paths, job_id)
    if completed.get("status") == "failed":
        failure_error = str(completed.get("error") or "pipeline reported failed progress event")
        failure_step = completed.get("current_step")
        completed["current_step"] = None
        completed["finished_at"] = _now_iso()
        completed["updated_at"] = _now_iso()
        completed["error"] = failure_error
        write_job(paths, completed)
        _backfill_job_metadata_if_workspace_known(paths, agent_config, job_id)
        _persist_asr_fallback_used(paths, job_id)
        notification = _notification_line(job_id, "FAILED", failure_error)
        _emit_notification(paths, job_id, notification)
        _append_failure_summary(
            paths,
            job_id,
            current_step=failure_step if isinstance(failure_step, str) else None,
            error=failure_error,
        )
        return True

    completed["status"] = "completed"
    completed["result_path"] = result_path
    completed["current_step"] = None
    completed["error"] = None
    completed["finished_at"] = _now_iso()
    completed["updated_at"] = _now_iso()
    write_job(paths, completed)
    _backfill_job_metadata_if_workspace_known(paths, agent_config, job_id)
    _persist_asr_fallback_used(paths, job_id)
    notification = _notification_line(job_id, "COMPLETED", str(result_path))
    _emit_notification(paths, job_id, notification)
    return True


def spawn_background_worker(paths: AgentPaths, *, base_config_path: str) -> subprocess.Popen:
    queue = read_queue(paths)
    queued_job_ids = queue.get("queued_job_ids", [])
    stdout_path = paths.logs_dir / "worker.log"
    with stdout_path.open("a", encoding="utf-8") as stdout_handle:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "yt2notion.cli",
                "agent",
                "_worker",
                "--agent-home",
                str(paths.home),
                "--config",
                base_config_path,
            ],
            cwd=str(paths.home),
            stdout=stdout_handle,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            text=True,
        )
    _write_worker_state(
        paths,
        pid=process.pid,
        job_id=queued_job_ids[0] if queued_job_ids else None,
        mode="background",
    )
    return process
