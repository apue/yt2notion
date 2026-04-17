# Minimal Agent Error Diagnosis Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the minimal `agent` error diagnosis slice so AI can find the latest failed job, read its log, explain the failure in plain Chinese, and clearly return `unknown` when no guide pattern matches.

**Architecture:** Keep the implementation intentionally small. Add one diagnosis guide, one repo-local skill that enforces the command workflow, and one local string-pattern classifier in the agent failure path that appends a `FAILURE SUMMARY` block to failed job logs. Use thin tests around failure-summary emission instead of heavy pipeline mocks.

**Tech Stack:** Python, pytest, Typer CLI, repo-local Codex skills, file-backed agent runtime logs

---

### Task 1: Add the Diagnosis Guide

**Files:**
- Create: `docs/agent-error-guide.md`
- Reference: `docs/superpowers/specs/2026-04-17-agent-error-diagnosis-minimal-design.md`

- [ ] **Step 1: Write the guide document content**

Write `docs/agent-error-guide.md` with these sections and exact bullets:

```md
# Agent Error Guide

## Goal

当用户说“帮我检查最近一次错误”时，AI 必须先找 job，再读 job metadata 和 log，再根据本文档翻译结论。

## Command Workflow

1. `uv run yt2notion agent list`
2. 找最近一个 `failed` 的 `job_id`
3. `uv run yt2notion agent show <job_id>`
4. `uv run yt2notion agent logs <job_id>`
5. 结合本文档输出结论

## Runtime Files

- `~/.yt2notion-agent/jobs/<job_id>.json`
- `~/.yt2notion-agent/logs/<job_id>.log`

## How to Read the Files

- `agent list`: 找最近 `failed`
- `agent show`: 看 `status`、`error`、`current_step`、`workspace_dir`
- `agent logs`: 看原始报错和尾部 `FAILURE SUMMARY`

## Error Catalog

| pattern | step | substep | meaning | retry advice | next action |
| --- | --- | --- | --- | --- | --- |
| `SSL: UNEXPECTED_EOF_WHILE_READING` | `download` | `metadata` | Apple 页面或 TLS 链路波动 | `safe` | 先重试；连续出现再检查 `yt-dlp`/网络/站点状态 |
| `HTTP Error 403: Forbidden` | `download` | `audio_download` | 音频源被 block、风控或 cookies/headers 不满足 | `limited` | 可有限重试；若持续复现，再检查 cookies 或提取逻辑 |
| `yt-dlp not found` | `download` | `tooling` | 本机缺少 `yt-dlp` 可执行文件 | `no` | 安装或修正运行环境 |
| `No subtitles and no ASR endpoint configured` | `transcribe` | `asr_config` | 没字幕，且没有可用 ASR 配置 | `no` | 补 `extract.asr.endpoint` 或调整提取策略 |
| `ASR request failed` | `transcribe` | `asr_request` | ASR 服务不可达或请求失败 | `limited` | 先看服务状态，再决定重试 |
| `Failed after 3 attempts: Command '['codex'` | `extract` or `summarize` | `codex_exec` | Codex CLI 调用反复失败 | `limited` | 先看 profile/model/config，再决定重试 |
| `profile` / `config` / `model` related Codex errors | `extract` or `summarize` | `codex_config` | Codex profile 或 model 配置无效 | `no` | 改配置，不要盲重试 |

## Unknown Error Handling

- 先保留原始错误短句
- 从 `agent show` 和 `agent logs` 判断失败节点
- 如果没有命中已知模式，明确返回 `unknown`
- 说明这代表需要后续补 guide 条目或补 log hint
```

- [ ] **Step 2: Save the guide**

Run:

```bash
test -f docs/agent-error-guide.md
```

Expected: command exits `0`

- [ ] **Step 3: Self-check the guide for scope**

Run:

```bash
rg -n "telemetry|dashboard|analytics|platform" docs/agent-error-guide.md
```

Expected: no output

### Task 2: Add the Repo-Local Diagnosis Skill

**Files:**
- Create: `.agents/skills/agent-error-diagnosis/SKILL.md`
- Reference: `docs/agent-error-guide.md`
- Reference: `.agents/skills/yt-extract/SKILL.md`

- [ ] **Step 1: Write the skill frontmatter and procedure**

Create `.agents/skills/agent-error-diagnosis/SKILL.md` with this structure:

```md
---
name: agent-error-diagnosis
description: Diagnose yt2notion agent failures by listing jobs, reading a failed job record and log, and translating the result with docs/agent-error-guide.md
---

# Agent Error Diagnosis

## Required Workflow

When the user asks to check a recent agent failure:

1. Run `uv run yt2notion agent list`
2. Choose the latest `failed` job unless the user gave a `job_id`
3. Run `uv run yt2notion agent show <job_id>`
4. Run `uv run yt2notion agent logs <job_id>`
5. Read `docs/agent-error-guide.md`
6. Answer using the format below

Do not:

- stop after `agent list`
- answer from memory
- modify code, logs, or docs during diagnosis
- force a known diagnosis when the log does not match the guide

If no known pattern matches, return `unknown` explicitly and recommend updating the guide or log hint logic later.

## Output Format

- 失败任务：
- 失败节点：
- 直接原因：
- 人话解释：
- 是否建议 retry：
- 下一步建议：
```

- [ ] **Step 2: Verify the skill file exists and points to the guide**

Run:

```bash
rg -n "agent-error-guide.md|uv run yt2notion agent list|unknown" .agents/skills/agent-error-diagnosis/SKILL.md
```

Expected: output includes all three phrases

- [ ] **Step 3: Self-check that the skill is diagnosis-only**

Run:

```bash
rg -n "modify code|logs|docs during diagnosis" .agents/skills/agent-error-diagnosis/SKILL.md
```

Expected: output includes the diagnosis-only rule

### Task 3: Append Failure Summary Blocks and Add Thin Tests

**Files:**
- Modify: `src/yt2notion/agent_worker.py`
- Modify: `tests/test_agent_worker.py`

- [ ] **Step 1: Write the failing tests for known and unknown failure summaries**

Add tests near the existing failure-path tests in `tests/test_agent_worker.py`:

```python
def test_run_worker_once_appends_known_failure_summary_for_extract_403(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig("/vault", "summaries", "transcripts", str(paths.workspace_dir), "gpt-5.4", "medium")

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=RuntimeError("yt-dlp failed: ERROR: unable to download video data: HTTP Error 403: Forbidden"),
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
    agent_cfg = AgentConfig("/vault", "summaries", "transcripts", str(paths.workspace_dir), "gpt-5.4", "medium")

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch(
            "yt2notion.agent_worker.run_pipeline",
            side_effect=RuntimeError("yt-dlp failed: ERROR: [ApplePodcasts] 100: Unable to download webpage: [SSL: UNEXPECTED_EOF_WHILE_READING] EOF occurred in violation of protocol"),
        ),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "step: download" in log_text
    assert "substep: metadata" in log_text
    assert "hint: ssl_eof" in log_text
    assert "retry: safe" in log_text


def test_run_worker_once_appends_unknown_failure_summary_when_pattern_is_new(tmp_path: Path) -> None:
    paths = ensure_agent_home(tmp_path)
    _seed_job(paths, "job-1")
    write_queue(paths, {"queued_job_ids": ["job-1"]})
    agent_cfg = AgentConfig("/vault", "summaries", "transcripts", str(paths.workspace_dir), "gpt-5.4", "medium")

    with (
        patch("yt2notion.agent_worker.build_runtime_app_config", return_value=object()),
        patch("yt2notion.agent_worker.run_pipeline", side_effect=RuntimeError("brand new failure shape")),
    ):
        assert run_worker_once(paths, agent_cfg, base_config_path="config.yaml") is True

    log_text = (paths.logs_dir / "job-1.log").read_text(encoding="utf-8")
    assert "=== FAILURE SUMMARY ===" in log_text
    assert "hint: unknown" in log_text
    assert "retry: unknown" in log_text
```

- [ ] **Step 2: Run the new tests to see them fail**

Run:

```bash
uv run pytest tests/test_agent_worker.py -q
```

Expected: the new failure-summary tests fail because the summary block does not exist yet

- [ ] **Step 3: Add a tiny local classifier in `agent_worker.py`**

Add helper functions near the existing log helpers:

```python
def _classify_failure_summary(error: str, *, current_step: str | None) -> tuple[str, str, str, str]:
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
    if "profile" in text or "reasoning_effort" in text or "model" in text and "codex" in text:
        return (step, "codex_config", "codex_config_invalid", "no")
    return (step, "-", "unknown", "unknown")


def _append_failure_summary(paths: AgentPaths, job_id: str, *, current_step: str | None, error: str) -> None:
    step, substep, hint, retry = _classify_failure_summary(error, current_step=current_step)
    append_job_log(paths, job_id, "=== FAILURE SUMMARY ===")
    append_job_log(paths, job_id, f"step: {step}")
    append_job_log(paths, job_id, f"substep: {substep}")
    append_job_log(paths, job_id, f"hint: {hint}")
    append_job_log(paths, job_id, f"retry: {retry}")
    append_job_log(paths, job_id, "=== END FAILURE SUMMARY ===")
```

- [ ] **Step 4: Call the summary appender from both failed paths**

Update both failure branches in `run_worker_once(...)`:

```python
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
        _append_failure_summary(
            paths,
            job_id,
            current_step=failure_step if isinstance(failure_step, str) else None,
            error=failure_error,
        )
```

And:

```python
    if completed.get("status") == "failed":
        failure_error = str(completed.get("error") or "pipeline reported failed progress event")
        failure_step = completed.get("current_step")
        completed["current_step"] = None
        completed["finished_at"] = _now_iso()
        completed["updated_at"] = _now_iso()
        completed["error"] = failure_error
        write_job(paths, completed)
        _append_failure_summary(
            paths,
            job_id,
            current_step=failure_step if isinstance(failure_step, str) else None,
            error=failure_error,
        )
```

- [ ] **Step 5: Run the targeted tests**

Run:

```bash
uv run pytest tests/test_agent_worker.py -q
```

Expected: all `tests/test_agent_worker.py` tests pass

- [ ] **Step 6: Run the broader agent regression tests**

Run:

```bash
uv run pytest tests/test_agent_worker.py tests/test_cli.py -q
```

Expected: full pass

### Task 4: Local Review and GitHub Workflow

**Files:**
- Verify only

- [ ] **Step 1: Run local checks before branching**

Run:

```bash
uv run pytest tests/test_agent_worker.py tests/test_cli.py -q
uv run ruff check src/yt2notion/agent_worker.py tests/test_agent_worker.py
```

Expected: both commands pass

- [ ] **Step 2: Do a local code self-review**

Review:

- `docs/agent-error-guide.md`
- `.agents/skills/agent-error-diagnosis/SKILL.md`
- `src/yt2notion/agent_worker.py`
- `tests/test_agent_worker.py`

Checklist:

- guide and skill agree on the command workflow
- unknown cases return `unknown`
- log hints stay short and stable
- no unrelated refactor slipped in

- [ ] **Step 3: Create the feature branch after local validation**

Run:

```bash
git checkout -b feat/agent-error-diagnosis
```

Expected: switched to a new branch

- [ ] **Step 4: Commit the implementation**

Run:

```bash
git add docs/agent-error-guide.md .agents/skills/agent-error-diagnosis/SKILL.md src/yt2notion/agent_worker.py tests/test_agent_worker.py handoff.md docs/superpowers/plans/2026-04-17-agent-error-diagnosis-minimal-implementation.md
git commit -m "Add minimal agent error diagnosis flow"
```

Expected: one clean commit for the implementation slice

- [ ] **Step 5: Push and create the PR with `gh`**

Run:

```bash
git push -u origin feat/agent-error-diagnosis
gh pr create --fill
```

Expected: PR URL is printed

- [ ] **Step 6: Perform code review and fix comments on the same branch**

Run:

```bash
gh pr view --comments
```

Expected: review comments are visible locally

Then fix the comments, rerun local tests, and update the branch:

```bash
uv run pytest tests/test_agent_worker.py tests/test_cli.py -q
uv run ruff check src/yt2notion/agent_worker.py tests/test_agent_worker.py
git add <updated-files>
git commit -m "Address PR review feedback"
git push
```

- [ ] **Step 7: Merge the PR and sync local `main`**

Run:

```bash
gh pr merge --squash --delete-branch
git checkout main
git pull --ff-only
```

Expected: PR merged, feature branch deleted remotely, local `main` is up to date

## Self-Review

- Spec coverage: all three deliverables from `docs/superpowers/specs/2026-04-17-agent-error-diagnosis-minimal-design.md` are mapped to Tasks 1-3, and the requested local/GitHub workflow is mapped to Task 4.
- Placeholder scan: no `TODO`, `TBD`, or deferred implementation language remains.
- Type consistency: the plan uses a single failure-summary helper flow in `src/yt2notion/agent_worker.py` and a single `unknown` fallback model across docs, skill, and tests.
