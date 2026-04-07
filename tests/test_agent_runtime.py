from __future__ import annotations

import json
from pathlib import Path

from yt2notion.agent_runtime import (
    AgentConfig,
    build_runtime_app_config,
    ensure_agent_home,
    load_agent_config,
    read_queue,
    write_job,
)


def test_ensure_agent_home_creates_runtime_files(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)

    assert paths.home == tmp_path
    assert paths.config_path.exists()
    assert paths.agents_path.exists()
    assert paths.queue_path.exists()
    assert paths.jobs_dir.is_dir()
    assert paths.logs_dir.is_dir()

    queue = json.loads(paths.queue_path.read_text(encoding="utf-8"))
    assert queue["queued_job_ids"] == []


def test_load_agent_config_reads_minimal_yaml(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    paths.config_path.write_text(
        "\n".join(
            [
                'vault_path: "/vault"',
                'summaries_dir: "notes/summaries"',
                'transcripts_dir: "notes/transcripts"',
                f'workspace_dir: "{tmp_path / "workspace"}"',
                'codex_model: "gpt-5.3-codex"',
                'reasoning_effort: "low"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_agent_config(paths)

    assert cfg == AgentConfig(
        vault_path="/vault",
        summaries_dir="notes/summaries",
        transcripts_dir="notes/transcripts",
        workspace_dir=str(tmp_path / "workspace"),
        codex_model="gpt-5.3-codex",
        reasoning_effort="low",
    )


def test_build_runtime_app_config_preserves_asr_settings(tmp_path: Path) -> None:
    vault = tmp_path / "vault"
    vault.mkdir()
    base_config = tmp_path / "config.yaml"
    base_config.write_text(
        "\n".join(
            [
                "model:",
                "  backend: claude_code",
                "storage:",
                "  backend: notion",
                "extract:",
                "  asr:",
                "    endpoint: http://127.0.0.1:8930",
                "    restart_before_transcribe: true",
                '    restart_command: "/tmp/restart-asr.sh host"',
            ]
        ),
        encoding="utf-8",
    )

    paths = ensure_agent_home(tmp_path / "agent-home")
    agent_cfg = AgentConfig(
        vault_path=str(vault),
        summaries_dir="summaries",
        transcripts_dir="transcripts",
        workspace_dir=str(paths.home / "workspace"),
        codex_model="gpt-5.3-codex",
        reasoning_effort="low",
    )
    app_cfg = build_runtime_app_config(str(base_config), agent_cfg, paths.home)

    assert app_cfg.model["backend"] == "codex_cli"
    assert app_cfg.storage["backend"] == "obsidian"
    assert app_cfg.output["mode"] == "summary"
    assert app_cfg.extract["asr"]["restart_before_transcribe"] is True
    assert app_cfg.extract["asr"]["restart_command"] == "/tmp/restart-asr.sh host"


def test_write_job_persists_json(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    record = {
        "job_id": "job-1",
        "url": "https://example.com",
        "status": "queued",
    }

    write_job(paths, record)

    saved = json.loads((paths.jobs_dir / "job-1.json").read_text(encoding="utf-8"))
    assert saved["status"] == "queued"
    assert read_queue(paths)["queued_job_ids"] == []


def test_load_agent_config_expands_user_paths_and_defaults_workspace(
    tmp_path: Path, monkeypatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    paths = ensure_agent_home(tmp_path / "agent-home")
    paths.config_path.write_text(
        "\n".join(
            [
                'vault_path: "~/vault"',
                'summaries_dir: "notes/summaries"',
                'transcripts_dir: "notes/transcripts"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_agent_config(paths)

    assert cfg.vault_path == str(fake_home / "vault")
    assert cfg.workspace_dir == str(paths.workspace_dir)


def test_build_runtime_app_config_uses_normalized_agent_config_paths(
    tmp_path: Path, monkeypatch
) -> None:
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    vault = fake_home / "vault"
    vault.mkdir()
    monkeypatch.setenv("HOME", str(fake_home))

    base_config = tmp_path / "config.yaml"
    base_config.write_text(
        "\n".join(
            [
                "model:",
                "  backend: claude_code",
                "storage:",
                "  backend: notion",
            ]
        ),
        encoding="utf-8",
    )

    paths = ensure_agent_home(tmp_path / "agent-home")
    explicit_workspace = fake_home / "custom-workspace"
    agent_cfg = AgentConfig(
        vault_path="~/vault",
        summaries_dir="summaries",
        transcripts_dir="transcripts",
        workspace_dir="~/custom-workspace",
        codex_model="gpt-5.3-codex",
        reasoning_effort="low",
    )
    app_cfg = build_runtime_app_config(str(base_config), agent_cfg, paths.home)

    assert app_cfg.storage["obsidian"]["vault_path"] == str(vault)
    assert app_cfg.workspace["base_dir"] == str(explicit_workspace)
    assert app_cfg.workspace["base_dir"] != str(paths.workspace_dir)


def test_build_runtime_app_config_fails_early_for_missing_vault_dir(tmp_path: Path) -> None:
    base_config = tmp_path / "config.yaml"
    base_config.write_text(
        "\n".join(
            [
                "model:",
                "  backend: claude_code",
                "storage:",
                "  backend: notion",
            ]
        ),
        encoding="utf-8",
    )

    paths = ensure_agent_home(tmp_path / "agent-home")
    agent_cfg = AgentConfig(
        vault_path=str(tmp_path / "missing-vault"),
        summaries_dir="summaries",
        transcripts_dir="transcripts",
        workspace_dir=str(paths.workspace_dir),
        codex_model="gpt-5.3-codex",
        reasoning_effort="low",
    )

    try:
        build_runtime_app_config(str(base_config), agent_cfg, paths.home)
    except ValueError as exc:
        assert "vault_path" in str(exc)
    else:
        raise AssertionError("Expected ValueError for missing vault directory")


def test_load_agent_config_anchors_relative_vault_path_to_agent_home(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path / "agent-home")
    relative_vault = paths.home / "vaults" / "main"
    relative_vault.mkdir(parents=True)
    paths.config_path.write_text(
        "\n".join(
            [
                'vault_path: "vaults/main"',
                'workspace_dir: "workspace-data"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_agent_config(paths)

    assert cfg.vault_path == str(relative_vault)


def test_load_agent_config_anchors_relative_workspace_path_to_agent_home(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path / "agent-home")
    paths.config_path.write_text(
        "\n".join(
            [
                f'vault_path: "{tmp_path / "vault"}"',
                'workspace_dir: "workspace-data"',
            ]
        ),
        encoding="utf-8",
    )

    cfg = load_agent_config(paths)

    assert cfg.workspace_dir == str(paths.home / "workspace-data")


def test_load_agent_config_rejects_non_string_path_values(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path / "agent-home")
    paths.config_path.write_text(
        "\n".join(
            [
                "vault_path: false",
                "workspace_dir: 123",
            ]
        ),
        encoding="utf-8",
    )

    try:
        load_agent_config(paths)
    except ValueError as exc:
        assert "must be a string path" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-string path values")


def test_load_agent_config_requires_top_level_mapping(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path / "agent-home")
    paths.config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")

    try:
        load_agent_config(paths)
    except ValueError as exc:
        assert "must contain a mapping/object" in str(exc)
    else:
        raise AssertionError("Expected ValueError for non-mapping agent.yaml")


def test_build_runtime_app_config_rejects_workspace_file_path(tmp_path: Path) -> None:
    base_config = tmp_path / "config.yaml"
    base_config.write_text(
        "\n".join(
            [
                "model:",
                "  backend: claude_code",
                "storage:",
                "  backend: notion",
            ]
        ),
        encoding="utf-8",
    )

    paths = ensure_agent_home(tmp_path / "agent-home")
    vault = tmp_path / "vault"
    vault.mkdir()
    workspace_file = tmp_path / "workspace.txt"
    workspace_file.write_text("not a dir", encoding="utf-8")
    agent_cfg = AgentConfig(
        vault_path=str(vault),
        summaries_dir="summaries",
        transcripts_dir="transcripts",
        workspace_dir=str(workspace_file),
        codex_model="gpt-5.3-codex",
        reasoning_effort="low",
    )

    try:
        build_runtime_app_config(str(base_config), agent_cfg, paths.home)
    except ValueError as exc:
        assert "workspace_dir" in str(exc)
    else:
        raise AssertionError("Expected ValueError for workspace_dir file path")
