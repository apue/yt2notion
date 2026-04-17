from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

from yt2notion.agent_runtime import (
    AgentConfig,
    ensure_agent_home,
    read_queue,
    write_job,
    write_queue,
)
from yt2notion.agent_worker import (
    claim_worker_slot,
    mark_stale_worker_failed,
    recover_orphaned_queued_jobs,
    retry_job,
    run_worker_once,
    spawn_background_worker,
)


def _seed_job(paths, job_id: str, *, status: str = "queued") -> None:
    write_job(
        paths,
        {
            "job_id": job_id,
            "url": "https://example.com/watch?v=abc",
            "status": status,
            "created_at": "2026-04-07T10:00:00+08:00",
            "updated_at": "2026-04-07T10:00:00+08:00",
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
        },
    )


def _read_job(paths, job_id: str) -> dict:
    return json.loads((paths.jobs_dir / f"{job_id}.json").read_text(encoding="utf-8"))


def test_run_worker_once_marks_success_and_result_path(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", return_value="/vault/summaries/note.md"),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    record = _read_job(paths, "job-1")
    assert record["status"] == "completed"
    assert record["result_path"] == "/vault/summaries/note.md"
    assert read_queue(paths)["queued_job_ids"] == []


def test_retry_job_creates_new_queued_job(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1", status="failed")

    new_job_id = retry_job(paths, "job-1")

    new_job = _read_job(paths, new_job_id)
    old_job = _read_job(paths, "job-1")
    assert new_job_id != "job-1"
    assert old_job["status"] == "failed"
    assert new_job["status"] == "queued"
    assert new_job["url"] == old_job["url"]
    assert read_queue(paths)["queued_job_ids"] == [new_job_id]


def test_mark_stale_worker_failed_marks_running_job(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1", status="running")
    paths.worker_path.write_text(
        json.dumps({"pid": 12345, "job_id": "job-1"}, indent=2),
        encoding="utf-8",
    )

    with patch("yt2notion.agent_worker._pid_alive", return_value=False):
        mark_stale_worker_failed(paths)

    record = _read_job(paths, "job-1")
    assert record["status"] == "failed"
    assert "worker process exited" in record["error"]
    assert not paths.worker_path.exists()


def test_mark_stale_worker_failed_handles_malformed_worker_state(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    paths.worker_path.write_text("{not-json", encoding="utf-8")

    mark_stale_worker_failed(paths)

    assert not paths.worker_path.exists()


def test_mark_stale_worker_failed_marks_claimed_queued_job(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1", status="queued")
    write_queue(paths, {"queued_job_ids": []})
    paths.worker_path.write_text(
        json.dumps({"pid": 12345, "job_id": "job-1"}, indent=2),
        encoding="utf-8",
    )

    with patch("yt2notion.agent_worker._pid_alive", return_value=False):
        mark_stale_worker_failed(paths)

    record = _read_job(paths, "job-1")
    assert record["status"] == "queued"
    assert read_queue(paths)["queued_job_ids"] == ["job-1"]
    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "REQUEUED after worker exited before start" in log_text
    assert not paths.worker_path.exists()


def test_run_worker_once_updates_job_via_progress_callback_and_writes_log(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    metadata_dir = paths.workspace_dir / "video-123"
    metadata_dir.mkdir(parents=True, exist_ok=True)
    (metadata_dir / "metadata.json").write_text(
        json.dumps(
            {
                "video_id": "video-123",
                "title": "Backfilled title",
                "channel": "Backfilled channel",
                "url": "https://example.com/watch?v=abc",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    other_metadata_dir = paths.workspace_dir / "video-other"
    other_metadata_dir.mkdir(parents=True, exist_ok=True)
    (other_metadata_dir / "metadata.json").write_text(
        json.dumps(
            {
                "video_id": "video-other",
                "title": "Wrong title",
                "channel": "Wrong channel",
                "url": "https://example.com/watch?v=other",
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    def _fake_run_pipeline(url, config, **kwargs):
        callback = kwargs["progress_callback"]
        callback("download", "started", "begin")
        callback("download", "completed", "done")
        callback("summarize", "started", "begin")
        callback("summarize", "completed", "done")
        return "/vault/summaries/final.md"

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=_fake_run_pipeline),
        patch("builtins.print") as mock_print,
    ):
        run_worker_once(paths, agent_cfg, base_config_path="config.yaml")

    record = _read_job(paths, "job-1")
    assert record["status"] == "completed"
    assert record["current_step"] is None
    assert record["completed_steps"] == ["download", "summarize"]
    assert record["workspace_dir"] == str(metadata_dir)
    assert record["video_id"] == "video-123"
    assert record["title"] == "Backfilled title"
    assert record["channel"] == "Backfilled channel"
    mock_print.assert_called_once_with("JOB job-1 COMPLETED /vault/summaries/final.md")

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "download:started begin" in log_text
    assert "download:completed done" in log_text
    assert "summarize:completed done" in log_text
    assert "JOB job-1 COMPLETED /vault/summaries/final.md" in log_text


def test_run_worker_once_keeps_worker_file_until_queue_drain_completes(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    _seed_job(paths, "job-2")
    write_queue(paths, {"queued_job_ids": ["job-1", "job-2"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=["/vault/summaries/1.md", "/vault/summaries/2.md"],
        ),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True
        worker_after_first = json.loads(paths.worker_path.read_text(encoding="utf-8"))
        assert worker_after_first["job_id"] == "job-1"

        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True
        worker_after_second = json.loads(paths.worker_path.read_text(encoding="utf-8"))
        assert worker_after_second["job_id"] == "job-2"

        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is False
        assert not paths.worker_path.exists()


def test_run_worker_once_handles_skipped_and_failed_progress_events(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    def _fake_run_pipeline(url, config, **kwargs):
        callback = kwargs["progress_callback"]
        callback("download", "started", "begin")
        callback("download", "completed", "done")
        callback("review", "skipped", "not needed")
        callback("summarize", "failed", "llm timeout")
        raise RuntimeError("pipeline exploded")

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=_fake_run_pipeline),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    record = _read_job(paths, "job-1")
    assert record["status"] == "failed"
    assert record["error"] == "pipeline exploded"
    assert record["current_step"] is None
    assert record["completed_steps"] == ["download"]

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "review:skipped not needed" in log_text
    assert "summarize:failed llm timeout" in log_text
    assert "FAILED pipeline exploded" in log_text


def test_run_worker_once_background_mode_captures_pipeline_stdout_stderr_to_job_log(
    tmp_path: Path,
) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    def _fake_run_pipeline(url, config, **kwargs):
        print("pipeline stdout line")
        print("pipeline stderr line", file=sys.stderr)
        return "/vault/summaries/final.md"

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=_fake_run_pipeline),
    ):
        assert (
            run_worker_once(
                paths,
                agent_cfg,
                base_config_path="config.yaml",
                capture_pipeline_output=True,
            )
            is True
        )

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "pipeline stdout line" in log_text
    assert "pipeline stderr line" in log_text
    assert "JOB job-1 COMPLETED /vault/summaries/final.md" in log_text


def test_background_notifications_are_written_to_each_job_log(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    _seed_job(paths, "job-2")
    write_queue(paths, {"queued_job_ids": ["job-1", "job-2"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=["/vault/summaries/1.md", "/vault/summaries/2.md"],
        ),
    ):
        assert (
            run_worker_once(
                paths,
                agent_cfg,
                base_config_path="config.yaml",
                capture_pipeline_output=True,
            )
            is True
        )
        assert (
            run_worker_once(
                paths,
                agent_cfg,
                base_config_path="config.yaml",
                capture_pipeline_output=True,
            )
            is True
        )

    assert "JOB job-1 COMPLETED /vault/summaries/1.md" in (paths.logs_dir / "job-1.log").read_text(
        encoding="utf-8"
    )
    assert "JOB job-2 COMPLETED /vault/summaries/2.md" in (paths.logs_dir / "job-2.log").read_text(
        encoding="utf-8"
    )


def test_spawn_background_worker_uses_active_job_log_when_queue_non_empty(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})

    with patch("yt2notion.agent_worker.subprocess.Popen") as mock_popen:
        mock_popen.return_value.pid = 43210
        spawn_background_worker(paths, base_config_path="/tmp/config.yaml")

    stdout_handle = mock_popen.call_args.kwargs["stdout"]
    assert Path(stdout_handle.name) == paths.logs_dir / "worker.log"
    worker_payload = json.loads(paths.worker_path.read_text(encoding="utf-8"))
    assert worker_payload["pid"] == 43210
    assert worker_payload["job_id"] == "job-1"


def test_recover_orphaned_queued_jobs_reenqueues_untracked_job(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1", status="queued")
    write_queue(paths, {"queued_job_ids": []})

    recover_orphaned_queued_jobs(paths)

    assert read_queue(paths)["queued_job_ids"] == ["job-1"]


def test_claim_worker_slot_is_exclusive(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)

    assert claim_worker_slot(paths, pid=111, job_id=None, mode="foreground") is True
    assert claim_worker_slot(paths, pid=222, job_id=None, mode="foreground") is False


def test_run_worker_once_persists_asr_fallback_used_on_success(tmp_path: Path) -> None:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    ws = Workspace(paths.workspace_dir, "video-1")
    ws.save_metadata(
        VideoMeta(
            video_id="video-1",
            title="Video 1",
            channel="Channel 1",
            url="https://example.com/watch?v=abc",
        )
    )
    ws.mark_asr_fallback_used()

    record = _read_job(paths, "job-1")
    record["workspace_dir"] = str(ws.dir)
    write_job(paths, record)

    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", return_value="/vault/summaries/note.md"),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    updated = _read_job(paths, "job-1")
    assert updated["status"] == "completed"
    assert updated["asr_fallback_used"] is True


def test_run_worker_once_persists_asr_fallback_used_on_failure(tmp_path: Path) -> None:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    ws = Workspace(paths.workspace_dir, "video-1")
    ws.save_metadata(
        VideoMeta(
            video_id="video-1",
            title="Video 1",
            channel="Channel 1",
            url="https://example.com/watch?v=abc",
        )
    )
    ws.mark_asr_fallback_used()
    record = _read_job(paths, "job-1")
    record["workspace_dir"] = str(ws.dir)
    write_job(paths, record)

    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=RuntimeError("pipeline failed")),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    updated = _read_job(paths, "job-1")
    assert updated["status"] == "failed"
    assert updated["asr_fallback_used"] is True


def test_run_worker_once_appends_known_failure_summary_for_extract_403(
    tmp_path: Path,
) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.4",
        "medium",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=RuntimeError(
                "yt-dlp failed: ERROR: unable to download video data: HTTP Error 403: Forbidden"
            ),
        ),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "=== FAILURE SUMMARY ===" in log_text
    assert "step: download" in log_text
    assert "substep: audio_download" in log_text
    assert "hint: source_forbidden" in log_text
    assert "retry: limited" in log_text


def test_run_worker_once_appends_known_failure_summary_for_ssl_eof(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.4",
        "medium",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=RuntimeError(
                "yt-dlp failed: ERROR: [ApplePodcasts] 100: Unable to download webpage: "
                "[SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"
            ),
        ),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "=== FAILURE SUMMARY ===" in log_text
    assert "step: download" in log_text
    assert "substep: metadata" in log_text
    assert "hint: ssl_eof" in log_text
    assert "retry: safe" in log_text


def test_run_worker_once_appends_unknown_failure_summary_when_pattern_is_new(
    tmp_path: Path,
) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.4",
        "medium",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=RuntimeError("brand new failure shape"),
        ),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "=== FAILURE SUMMARY ===" in log_text
    assert "hint: unknown" in log_text
    assert "retry: unknown" in log_text


def test_run_worker_once_failure_does_not_misattributed_old_workspace_fallback_by_url(
    tmp_path: Path,
) -> None:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})

    old_ws = Workspace(paths.workspace_dir, "old-video")
    old_ws.save_metadata(
        VideoMeta(
            video_id="old-video",
            title="Old Title",
            channel="Old Channel",
            url="https://example.com/watch?v=abc",
        )
    )
    old_ws.mark_asr_fallback_used()

    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=RuntimeError("pipeline failed")),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    updated = _read_job(paths, "job-1")
    assert updated["status"] == "failed"
    assert updated["asr_fallback_used"] is False


def test_run_worker_once_does_not_inherit_fallback_marker_from_old_workspace_on_early_failure(
    tmp_path: Path,
) -> None:
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})

    old_ws = Workspace(paths.workspace_dir, "video-old")
    old_ws.save_metadata(
        VideoMeta(
            video_id="video-old",
            title="Old Video",
            channel="Old Channel",
            url="https://example.com/watch?v=abc",
        )
    )
    old_ws.mark_asr_fallback_used()

    agent_cfg = AgentConfig(
        "/vault",
        "summaries",
        "transcripts",
        str(paths.workspace_dir),
        "gpt-5.3-codex",
        "low",
    )

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=RuntimeError("early failure")),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    updated = _read_job(paths, "job-1")
    assert updated["status"] == "failed"
    assert updated["workspace_dir"] is None
    assert updated["video_id"] is None
    assert updated["title"] is None
    assert updated["channel"] is None
    assert updated["asr_fallback_used"] is False
