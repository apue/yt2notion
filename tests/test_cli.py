"""Tests for CLI entry point."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from yt2notion.cli import app

runner = CliRunner()


def _write_job(agent_home: Path, record: dict) -> None:
    jobs_dir = agent_home / "jobs"
    jobs_dir.mkdir(parents=True, exist_ok=True)
    (jobs_dir / f"{record['job_id']}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def test_cli_help():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "YouTube" in result.output


def test_cli_missing_config():
    result = runner.invoke(
        app, ["process", "https://www.youtube.com/watch?v=abc", "-c", "/nonexistent/config.yaml"]
    )
    # Typer returns 2 for usage errors
    assert result.exit_code in (1, 2)
    assert "Configuration error" in result.output or "not found" in result.output


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_dry_run(mock_create_app, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    app_instance = MagicMock()
    app_instance.process.return_value = "dry run output"
    mock_create_app.return_value = app_instance

    result = runner.invoke(
        app,
        ["process", "https://www.youtube.com/watch?v=abc123", "--dry-run"],
    )
    # Typer may return 0 or other code for successful dry run
    if result.exit_code != 0:
        # If there's an error, print it for debugging
        print(result.output)
    assert result.exit_code == 0
    app_instance.process.assert_called_once()
    call_kwargs = app_instance.process.call_args
    assert call_kwargs.kwargs.get("dry_run") is True


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_process_invocation(mock_create_app, mock_load_config):
    from yt2notion.config import AppConfig

    mock_load_config.return_value = AppConfig()
    app_instance = MagicMock()
    app_instance.process.return_value = "https://notion.so/page123"
    mock_create_app.return_value = app_instance

    result = runner.invoke(
        app,
        [
            "process",
            "https://www.youtube.com/watch?v=abc123",
            "-v",
            "--mode",
            "full",
        ],
    )
    # Typer may return 0 or other code depending on pipeline output
    if result.exit_code != 0:
        # If there's an error, print it for debugging
        print(result.output)
    assert result.exit_code == 0
    call_kwargs = app_instance.process.call_args
    assert call_kwargs.kwargs.get("verbose") is True
    assert call_kwargs.kwargs.get("mode") == "full"


@patch("yt2notion.cli.load_config")
@patch("yt2notion.cli.create_yt2notion")
def test_cli_prepare_outputs_bundle_json(mock_create_app, mock_load_config, tmp_path):
    from yt2notion.application import PreparedContent
    from yt2notion.config import AppConfig
    from yt2notion.models.base import NoteBundle, NoteDocument, VideoMeta
    from yt2notion.workspace import Workspace

    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    bundle = NoteBundle(
        source=NoteDocument(title="Source", markdown="# Source", tags=["stable"], variant="source"),
        guide=NoteDocument(title="Guide", markdown="# Guide", tags=["guide"], variant="a_guide"),
        longform=NoteDocument(
            title="Long", markdown="# Long", tags=["long"], variant="b_longform"
        ),
        stable_tags=["stable"],
        source_topics=["topic"],
    )
    app_instance = MagicMock()
    app_instance.prepare.return_value = PreparedContent(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://www.youtube.com/watch?v=abc123",
        ),
        note_bundle=bundle,
        workspace=workspace,
        is_long=False,
    )
    mock_create_app.return_value = app_instance

    result = runner.invoke(
        app,
        ["prepare", "https://www.youtube.com/watch?v=abc123", "--mode", "summary"],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["mode"] == "bundle"
    assert payload["workspace_dir"] == str(workspace.dir)
    assert payload["note_bundle"]["source"]["variant"] == "source"
    assert payload["note_bundle"]["guide"]["variant"] == "a_guide"
    assert payload["note_bundle"]["longform"]["variant"] == "b_longform"


@patch("yt2notion.media_transcribe.transcribe_media")
@patch("yt2notion.media_transcribe.resolve_media_transcribe_config_path")
@patch("yt2notion.cli.load_config")
def test_cli_transcribe_outputs_json(
    mock_load_config,
    mock_resolve_config,
    mock_transcribe_media,
    tmp_path,
):
    from yt2notion.config import AppConfig
    from yt2notion.media_transcribe import MediaTranscribeResult
    from yt2notion.models.base import VideoMeta
    from yt2notion.workspace import Workspace

    config_path = tmp_path / "config.yaml"
    mock_resolve_config.return_value = config_path
    mock_load_config.return_value = AppConfig()
    workspace = Workspace(tmp_path, "abc123")
    result_payload = MediaTranscribeResult(
        metadata=VideoMeta(
            video_id="abc123",
            title="Test Video",
            channel="TestChannel",
            url="https://example.com/video",
        ),
        workspace=workspace,
        video_path=workspace.dir / "video.mp4",
        audio_path=workspace.dir / "audio.mp3",
        transcripts_path=workspace.dir / "transcripts.json",
        transcript_markdown_path=workspace.dir / "transcript.md",
    )
    mock_transcribe_media.return_value = result_payload

    result = runner.invoke(
        app,
        [
            "transcribe",
            "https://example.com/video",
            "--config",
            str(config_path),
            "--workspace-dir",
            str(tmp_path / "workspace"),
            "--no-video",
            "--json",
        ],
    )

    assert result.exit_code == 0
    payload = json.loads(result.output)
    assert payload["workspace_dir"] == str(workspace.dir)
    assert payload["transcript_markdown_path"] == str(workspace.dir / "transcript.md")
    mock_resolve_config.assert_called_once_with(str(config_path))
    mock_transcribe_media.assert_called_once()
    call_kwargs = mock_transcribe_media.call_args.kwargs
    assert call_kwargs["workspace_dir"] == str(tmp_path / "workspace")
    assert call_kwargs["keep_video"] is False


def test_agent_init_creates_runtime_home_without_starting_worker(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"

    with patch("yt2notion.cli.spawn_background_worker") as mock_spawn:
        result = runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    assert result.exit_code == 0
    assert (agent_home / "agent.yaml").exists()
    assert (agent_home / "config.yaml").exists()
    assert (agent_home / "AGENTS.md").exists()
    assert (agent_home / "queue.json").exists()
    assert not (agent_home / "worker.json").exists()
    mock_spawn.assert_not_called()


def test_agent_init_marks_stale_worker_before_returning(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"

    with patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale:
        result = runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    assert result.exit_code == 0
    mock_mark_stale.assert_called_once()


def test_agent_add_creates_job_and_starts_worker_when_idle(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"

    with patch("yt2notion.cli.spawn_background_worker") as mock_spawn:
        result = runner.invoke(
            app,
            [
                "agent",
                "add",
                "https://example.com/watch?v=abc123",
                "--agent-home",
                str(agent_home),
                "--config",
                "config.yaml",
            ],
        )

    assert result.exit_code == 0
    queue_payload = json.loads((agent_home / "queue.json").read_text(encoding="utf-8"))
    queued_ids = queue_payload["queued_job_ids"]
    assert len(queued_ids) == 1

    job_id = queued_ids[0]
    job_payload = json.loads((agent_home / "jobs" / f"{job_id}.json").read_text(encoding="utf-8"))
    assert job_payload["url"] == "https://example.com/watch?v=abc123"
    assert job_payload["status"] == "queued"
    mock_spawn.assert_called_once()
    assert Path(mock_spawn.call_args.kwargs["base_config_path"]).is_absolute()


def test_agent_add_defaults_to_runtime_config_in_agent_home_when_config_omitted(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"

    with (
        patch("yt2notion.cli._validate_agent_config_path", side_effect=lambda value: value)
        as mock_validate,
        patch("yt2notion.cli._start_worker_if_idle", return_value=False),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "add",
                "https://example.com/watch?v=abc123",
                "--agent-home",
                str(agent_home),
            ],
        )

    assert result.exit_code == 0
    assert mock_validate.call_args.args[0] == str(agent_home / "config.yaml")


def test_agent_add_prefers_explicit_config_over_runtime_default(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    explicit_config = tmp_path / "explicit-config.yaml"

    with (
        patch("yt2notion.cli._validate_agent_config_path", side_effect=lambda value: value)
        as mock_validate,
        patch("yt2notion.cli._start_worker_if_idle", return_value=False),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "add",
                "https://example.com/watch?v=abc123",
                "--agent-home",
                str(agent_home),
                "--config",
                str(explicit_config),
            ],
        )

    assert result.exit_code == 0
    assert mock_validate.call_args.args[0] == str(explicit_config)


def test_agent_status_reports_idle_queue_summary(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    result = runner.invoke(app, ["agent", "status", "--agent-home", str(agent_home)])

    assert result.exit_code == 0
    assert "Worker: idle" in result.output
    assert "Active Job: -" in result.output
    assert "Active Step: -" in result.output
    assert "Queued Jobs: 0" in result.output
    assert "Recent Outcomes:\n-" in result.output


def test_agent_init_uses_env_home_when_option_missing(tmp_path: Path, monkeypatch) -> None:
    env_home = tmp_path / "env-agent-home"
    monkeypatch.setenv("YT2NOTION_AGENT_HOME", str(env_home))

    result = runner.invoke(app, ["agent", "init"])

    assert result.exit_code == 0
    assert result.output.strip() == str(env_home)
    assert (env_home / "agent.yaml").exists()


def test_agent_init_option_overrides_env_home(tmp_path: Path, monkeypatch) -> None:
    env_home = tmp_path / "env-agent-home"
    option_home = tmp_path / "option-agent-home"
    monkeypatch.setenv("YT2NOTION_AGENT_HOME", str(env_home))

    result = runner.invoke(app, ["agent", "init", "--agent-home", str(option_home)])

    assert result.exit_code == 0
    assert result.output.strip() == str(option_home)
    assert (option_home / "agent.yaml").exists()
    assert not env_home.exists()


def test_agent_add_requires_existing_config_before_queue_mutation(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    before_queue = json.loads((agent_home / "queue.json").read_text(encoding="utf-8"))

    result = runner.invoke(
        app,
        [
            "agent",
            "add",
            "https://example.com/watch?v=abc123",
            "--agent-home",
            str(agent_home),
            "--config",
            str(tmp_path / "missing-config.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Configuration error" in result.output
    after_queue = json.loads((agent_home / "queue.json").read_text(encoding="utf-8"))
    assert after_queue["queued_job_ids"] == before_queue["queued_job_ids"] == []
    assert list((agent_home / "jobs").glob("*.json")) == []


def test_agent_add_marks_stale_worker_even_when_config_is_missing(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    with patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale:
        result = runner.invoke(
            app,
            [
                "agent",
                "add",
                "https://example.com/watch?v=abc123",
                "--agent-home",
                str(agent_home),
                "--config",
                str(tmp_path / "missing-config.yaml"),
            ],
        )

    assert result.exit_code == 1
    mock_mark_stale.assert_called_once()


def test_agent_status_reports_running_worker_and_recent_outcomes(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-queued-1", "job-queued-2"]}, indent=2),
        encoding="utf-8",
    )
    _write_job(
        agent_home,
        {
            "job_id": "job-running",
            "url": "https://example.com/running",
            "status": "running",
            "created_at": "2026-04-07T10:00:00+08:00",
            "updated_at": "2026-04-07T10:03:00+08:00",
            "started_at": "2026-04-07T10:01:00+08:00",
            "finished_at": None,
            "current_step": "transcribe",
            "completed_steps": ["download", "segment"],
            "workspace_dir": None,
            "video_id": None,
            "title": "Running title",
            "channel": "Running channel",
            "result_path": None,
            "error": None,
        },
    )
    _write_job(
        agent_home,
        {
            "job_id": "job-completed",
            "url": "https://example.com/completed",
            "status": "completed",
            "created_at": "2026-04-07T09:00:00+08:00",
            "updated_at": "2026-04-07T10:02:00+08:00",
            "started_at": "2026-04-07T09:01:00+08:00",
            "finished_at": "2026-04-07T10:02:00+08:00",
            "current_step": None,
            "completed_steps": ["download", "segment", "transcribe", "extract", "summarize"],
            "workspace_dir": None,
            "video_id": None,
            "title": "Completed title",
            "channel": "Completed channel",
            "result_path": "/vault/summaries/ok.md",
            "error": None,
        },
    )
    _write_job(
        agent_home,
        {
            "job_id": "job-failed",
            "url": "https://example.com/failed",
            "status": "failed",
            "created_at": "2026-04-07T08:00:00+08:00",
            "updated_at": "2026-04-07T10:01:00+08:00",
            "started_at": "2026-04-07T08:01:00+08:00",
            "finished_at": "2026-04-07T10:01:00+08:00",
            "current_step": "summarize",
            "completed_steps": ["download", "segment", "transcribe", "extract"],
            "workspace_dir": None,
            "video_id": None,
            "title": "Failed title",
            "channel": "Failed channel",
            "result_path": None,
            "error": "boom",
        },
    )
    (agent_home / "worker.json").write_text(
        json.dumps(
            {
                "pid": os.getpid(),
                "job_id": "job-running",
                "started_at": "2026-04-07T10:01:00+08:00",
                "mode": "background",
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    result = runner.invoke(app, ["agent", "status", "--agent-home", str(agent_home)])

    assert result.exit_code == 0
    assert "Worker: running" in result.output
    assert "Active Job: job-running" in result.output
    assert "Active Step: transcribe" in result.output
    assert "Queued Jobs: 2" in result.output
    assert (
        "job-completed\tcompleted\t2026-04-07T10:02:00+08:00\t/vault/summaries/ok.md"
        in result.output
    )
    assert "job-failed\tfailed\t2026-04-07T10:01:00+08:00\tboom" in result.output


def test_agent_list_show_and_logs_commands(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "completed",
            "created_at": "2026-04-07T10:00:00+08:00",
            "updated_at": "2026-04-07T10:02:00+08:00",
            "started_at": "2026-04-07T10:01:00+08:00",
            "finished_at": "2026-04-07T10:02:00+08:00",
            "current_step": None,
            "completed_steps": ["download", "segment", "transcribe", "extract", "summarize"],
            "workspace_dir": None,
            "video_id": None,
            "title": "Title 1",
            "channel": "Channel 1",
            "result_path": "/vault/summaries/1.md",
            "error": None,
            "asr_fallback_used": True,
        },
    )
    _write_job(
        agent_home,
        {
            "job_id": "job-2",
            "url": "https://example.com/2",
            "status": "running",
            "created_at": "2026-04-07T10:03:00+08:00",
            "updated_at": "2026-04-07T10:04:00+08:00",
            "started_at": "2026-04-07T10:03:00+08:00",
            "finished_at": None,
            "current_step": "extract",
            "completed_steps": ["download", "segment", "transcribe"],
            "workspace_dir": None,
            "video_id": None,
            "title": None,
            "channel": None,
            "result_path": None,
            "error": None,
            "asr_fallback_used": False,
        },
    )
    (agent_home / "logs" / "job-2.log").write_text("line-1\nline-2\n", encoding="utf-8")

    list_result = runner.invoke(app, ["agent", "list", "--agent-home", str(agent_home)])
    assert list_result.exit_code == 0
    list_lines = list_result.output.strip().splitlines()
    assert list_lines[0] == "job_id\tstatus\ttitle_or_url\tcurrent_step_or_result\tupdated_at"
    assert list_lines[1].startswith(
        "job-2\trunning\thttps://example.com/2\textract\t2026-04-07T10:04:00+08:00"
    )
    assert list_lines[2].startswith(
        "job-1\tcompleted\tTitle 1\t/vault/summaries/1.md\t2026-04-07T10:02:00+08:00"
    )

    show_result = runner.invoke(app, ["agent", "show", "job-1", "--agent-home", str(agent_home)])
    assert show_result.exit_code == 0
    show_payload = json.loads(show_result.output)
    assert show_payload["job_id"] == "job-1"
    assert show_payload["result_path"] == "/vault/summaries/1.md"
    assert show_payload["asr_fallback_used"] is True

    logs_result = runner.invoke(app, ["agent", "logs", "job-2", "--agent-home", str(agent_home)])
    assert logs_result.exit_code == 0
    assert logs_result.output == "line-1\nline-2\n"


def test_agent_run_foreground_requires_existing_config_before_drain(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "run",
            "--foreground",
            "--agent-home",
            str(agent_home),
            "--config",
            str(tmp_path / "missing-config.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Configuration error" in result.output
    queue_payload = json.loads((agent_home / "queue.json").read_text(encoding="utf-8"))
    assert queue_payload["queued_job_ids"] == ["job-1"]


def test_agent_run_foreground_marks_stale_worker_before_missing_config_error(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale:
        result = runner.invoke(
            app,
            [
                "agent",
                "run",
                "--foreground",
                "--agent-home",
                str(agent_home),
                "--config",
                str(tmp_path / "missing-config.yaml"),
            ],
        )

    assert result.exit_code == 1
    mock_mark_stale.assert_called_once()


def test_agent_run_foreground_marks_stale_worker_before_drain(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with (
        patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale,
        patch("yt2notion.cli.load_runtime_agent_config", return_value=object()),
        patch("yt2notion.cli.run_worker_once", side_effect=[False]) as mock_run_once,
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "run",
                "--foreground",
                "--agent-home",
                str(agent_home),
                "--config",
                "config.yaml",
            ],
        )

    assert result.exit_code == 0
    mock_mark_stale.assert_called_once()
    assert mock_run_once.call_count == 1


def test_agent_run_foreground_defaults_to_runtime_config_in_agent_home(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with (
        patch("yt2notion.cli._validate_agent_config_path", side_effect=lambda value: value)
        as mock_validate,
        patch("yt2notion.cli.claim_worker_slot", return_value=True),
        patch("yt2notion.cli._drain_queue"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "run",
                "--foreground",
                "--agent-home",
                str(agent_home),
            ],
        )

    assert result.exit_code == 0
    assert mock_validate.call_args.args[0] == str(agent_home / "config.yaml")


def test_agent_worker_entrypoint_requires_existing_config_before_drain(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "_worker",
            "--agent-home",
            str(agent_home),
            "--config",
            str(tmp_path / "missing-config.yaml"),
        ],
    )

    assert result.exit_code == 1
    assert "Configuration error" in result.output
    queue_payload = json.loads((agent_home / "queue.json").read_text(encoding="utf-8"))
    assert queue_payload["queued_job_ids"] == ["job-1"]


def test_agent_worker_entrypoint_marks_stale_worker_before_missing_config_error(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    with patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale:
        result = runner.invoke(
            app,
            [
                "agent",
                "_worker",
                "--agent-home",
                str(agent_home),
                "--config",
                str(tmp_path / "missing-config.yaml"),
            ],
        )

    assert result.exit_code == 1
    mock_mark_stale.assert_called_once()


def test_agent_hidden_worker_entrypoint_drains_queue(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with (
        patch("yt2notion.cli.load_runtime_agent_config", return_value=object()),
        patch("yt2notion.cli.run_worker_once", side_effect=[True, True, False]) as mock_run_once,
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "_worker",
                "--agent-home",
                str(agent_home),
                "--config",
                "config.yaml",
            ],
        )

    assert result.exit_code == 0
    assert mock_run_once.call_count == 3


def test_agent_hidden_worker_entrypoint_marks_stale_worker_before_drain(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "queued",
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
        },
    )
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with (
        patch("yt2notion.cli.mark_stale_worker_failed") as mock_mark_stale,
        patch("yt2notion.cli.load_runtime_agent_config", return_value=object()),
        patch("yt2notion.cli.run_worker_once", side_effect=[False]) as mock_run_once,
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "_worker",
                "--agent-home",
                str(agent_home),
                "--config",
                "config.yaml",
            ],
        )

    assert result.exit_code == 0
    mock_mark_stale.assert_called_once()
    assert mock_run_once.call_count == 1


def test_agent_worker_entrypoint_defaults_to_runtime_config_in_agent_home(
    tmp_path: Path,
) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    (agent_home / "queue.json").write_text(
        json.dumps({"queued_job_ids": ["job-1"]}),
        encoding="utf-8",
    )

    with (
        patch("yt2notion.cli._validate_agent_config_path", side_effect=lambda value: value)
        as mock_validate,
        patch("yt2notion.cli.claim_worker_slot", return_value=True),
        patch("yt2notion.cli._drain_queue"),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "_worker",
                "--agent-home",
                str(agent_home),
            ],
        )

    assert result.exit_code == 0
    assert mock_validate.call_args.args[0] == str(agent_home / "config.yaml")


def test_agent_retry_returns_clean_error_for_non_failed_job(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])
    _write_job(
        agent_home,
        {
            "job_id": "job-1",
            "url": "https://example.com/1",
            "status": "completed",
            "created_at": "2026-04-07T10:00:00+08:00",
            "updated_at": "2026-04-07T10:02:00+08:00",
            "started_at": "2026-04-07T10:01:00+08:00",
            "finished_at": "2026-04-07T10:02:00+08:00",
            "current_step": None,
            "completed_steps": ["download", "segment", "transcribe", "extract", "summarize"],
            "workspace_dir": None,
            "video_id": None,
            "title": "Title 1",
            "channel": "Channel 1",
            "result_path": "/vault/summaries/1.md",
            "error": None,
        },
    )

    result = runner.invoke(
        app,
        [
            "agent",
            "retry",
            "job-1",
            "--agent-home",
            str(agent_home),
            "--config",
            "config.yaml",
        ],
    )

    assert result.exit_code == 1
    assert "Only failed jobs can be retried" in result.output


def test_agent_retry_defaults_to_runtime_config_in_agent_home(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    with (
        patch("yt2notion.cli._validate_agent_config_path", side_effect=lambda value: value)
        as mock_validate,
        patch("yt2notion.cli.retry_job", return_value="job-2"),
        patch("yt2notion.cli._start_worker_if_idle", return_value=False),
    ):
        result = runner.invoke(
            app,
            [
                "agent",
                "retry",
                "job-1",
                "--agent-home",
                str(agent_home),
            ],
        )

    assert result.exit_code == 0
    assert mock_validate.call_args.args[0] == str(agent_home / "config.yaml")


def test_agent_retry_returns_clean_error_for_unknown_job(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    result = runner.invoke(
        app,
        [
            "agent",
            "retry",
            "missing-job",
            "--agent-home",
            str(agent_home),
            "--config",
            "config.yaml",
        ],
    )

    assert result.exit_code == 1
    assert "No such file or directory" in result.output


def test_agent_show_rejects_invalid_job_id(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    result = runner.invoke(app, ["agent", "show", "../worker", "--agent-home", str(agent_home)])

    assert result.exit_code == 1
    assert "Invalid job id" in result.output


def test_agent_run_background_does_not_spawn_when_queue_empty(tmp_path: Path) -> None:
    agent_home = tmp_path / "agent-home"
    runner.invoke(app, ["agent", "init", "--agent-home", str(agent_home)])

    with patch("yt2notion.cli.spawn_background_worker") as mock_spawn:
        result = runner.invoke(
            app,
            [
                "agent",
                "run",
                "--agent-home",
                str(agent_home),
                "--config",
                "config.yaml",
            ],
        )

    assert result.exit_code == 0
    assert result.output.strip() == "queue empty"
    mock_spawn.assert_not_called()
