# File-Backed CLI Agent for Codex + Obsidian

## Goal

Add a lightweight CLI agent layer on top of the existing `yt2notion` pipeline so the user can:

1. enqueue interesting YouTube / podcast URLs one by one,
2. let a local worker process them sequentially,
3. inspect queue and per-job progress at any time,
4. receive terminal-visible completion / failure notifications,
5. store finished output into an Obsidian vault automatically.

This agent must stay file-backed and command-triggered. No long-lived daemon, no service manager, no `full` mode.

## Product Constraints

These are fixed for this project, not user-tunable in the first version:

- LLM backend: `codex_cli`
- Storage backend: `obsidian`
- Output mode: `summary`
- Execution model: one local worker process at a time
- Trigger model: CLI commands plus a short-lived background worker, not a permanent daemon

The user has explicitly chosen automatic Obsidian writes for this agent workflow. That approval is limited to the configured local Obsidian vault and does not generalize to Notion or other backends.

## Scope

### In Scope

- A new `agent` CLI command group inside the existing repo
- A file-backed queue and per-job state model
- Minimal runtime config via `agent.yaml`
- A dedicated runtime `AGENTS.md` for Codex executions used by the agent
- Progress tracking for queued / running / completed / failed jobs
- Terminal-visible notifications
- Reuse of the existing pipeline for actual content processing and Obsidian publishing

### Out of Scope

- A separate installable package or Homebrew distribution
- System notifications (`terminal-notifier`, Notification Center, etc.)
- Parallel workers
- `full` transcript mode
- Notion publishing
- Clipboard or OS share-sheet ingestion
- Rich TUI / interactive dashboard

## User Experience

### MVP Invocation Model

The first implementation lives inside the existing CLI:

```bash
uv run yt2notion agent init
uv run yt2notion agent add "https://www.youtube.com/watch?v=..."
uv run yt2notion agent status
uv run yt2notion agent list
uv run yt2notion agent show <job-id>
uv run yt2notion agent logs <job-id>
uv run yt2notion agent retry <job-id>
uv run yt2notion agent run --foreground
```

This keeps implementation cheap while preserving the final product shape. A future standalone `yt-agent` wrapper can call the same internal command handlers.

### Expected Flow

1. User runs `agent init` once to create runtime config and runtime Codex instructions.
2. User runs `agent add <url>`.
3. The command creates a job, appends it to the queue, and starts a background worker if none is active.
4. The worker drains the queue sequentially by invoking the existing pipeline with the fixed runtime constraints.
5. The user can run `status`, `list`, `show`, or `logs` from any shell while work is in progress.
6. On completion or failure, the worker writes a terminal-readable notification line to the job log and stdout/stderr of the worker process.

### Non-Goals for UX

- The user should not need to understand `yt2notion`'s full `config.yaml`.
- The user should not need to remember the repo's development `AGENTS.md`.
- The user should not need to keep a foreground process attached for normal usage.

## Runtime Control Plane

The runtime agent must not reuse the repository root `AGENTS.md` or `config.yaml` as its control surface.

### Runtime Home

Use a dedicated agent home directory:

```text
~/.yt2notion-agent/
  agent.yaml
  AGENTS.md
  queue.json
  worker.json
  jobs/
    <job-id>.json
  logs/
    <job-id>.log
  workspace/
    <video-id>/
```

Notes:

- `~/.yt2notion-agent/` is simple, explicit, and works for MVP plus future global usage.
- A future standalone CLI can reuse the same directory unchanged.
- Add `--agent-home` and `YT2NOTION_AGENT_HOME` override support for testing.

### Runtime `AGENTS.md`

The runtime `AGENTS.md` is separate from the repo's development `AGENTS.md`.

Its purpose is narrow:

- Codex is being used as a text-processing backend inside a media pipeline
- Obsidian publishing is allowed only to the configured local vault
- `summary` mode only
- no autonomous code changes, no repository tasks, no internet browsing
- preserve source attribution in outputs

Implementation detail: Codex subprocesses used by the agent must run with `cwd=<agent_home>` so they see the runtime `AGENTS.md` instead of the repository development instructions.

## Minimal `agent.yaml`

The user requested an intentionally small config surface.

```yaml
vault_path: "/Users/you/Documents/Obsidian"
summaries_dir: "yt2notion/summaries"
transcripts_dir: "yt2notion/transcripts"
workspace_dir: "~/.yt2notion-agent/workspace"
codex_model: "gpt-5.3-codex"
reasoning_effort: "low"
```

### Config Rules

- No backend choice in `agent.yaml`; backend is fixed internally.
- No `mode` choice; always `summary`.
- No Notion fields.
- No advanced pipeline knobs in MVP.

### Internal Expansion

The agent runner converts `agent.yaml` into the existing `AppConfig` shape before invoking pipeline code:

- `model.backend = "codex_cli"`
- `model.summarize_model = codex_model`
- `model.translate_model = codex_model`
- `model.review_model = codex_model`
- `model.reasoning_effort = reasoning_effort`
- `storage.backend = "obsidian"`
- `storage.obsidian.*` from `agent.yaml`
- `output.mode = "summary"`
- `workspace.base_dir = workspace_dir`

This keeps user config minimal while preserving the current internal factories.

## Queue and Job Model

### Queue Semantics

- Single FIFO queue
- One running job at a time
- New jobs append to the tail
- Failed jobs remain in history and are re-queued only by explicit `retry`
- No automatic deduplication in MVP

### Job Lifecycle

Each job moves through these states:

- `queued`
- `starting`
- `running`
- `completed`
- `failed`

Optional future states such as `cancelled` stay out of MVP.

### Job Identity

Use a CLI-friendly generated job id such as:

```text
20260407-112233-a1b2
```

This is independent of the video id because enqueue happens before metadata is downloaded.

## State Files

### `queue.json`

Canonical queue file:

```json
{
  "queued_job_ids": ["20260407-112233-a1b2"],
  "updated_at": "2026-04-07T11:22:33+08:00"
}
```

### `worker.json`

Tracks the current worker process:

```json
{
  "pid": 12345,
  "started_at": "2026-04-07T11:22:40+08:00",
  "job_id": "20260407-112233-a1b2",
  "mode": "background"
}
```

This file is authoritative only if the PID is still alive.

### `jobs/<job-id>.json`

Canonical per-job state:

```json
{
  "job_id": "20260407-112233-a1b2",
  "url": "https://www.youtube.com/watch?v=...",
  "status": "running",
  "created_at": "2026-04-07T11:22:33+08:00",
  "updated_at": "2026-04-07T11:24:10+08:00",
  "started_at": "2026-04-07T11:22:40+08:00",
  "finished_at": null,
  "current_step": "summarize",
  "completed_steps": ["download", "segment", "transcribe", "extract"],
  "workspace_dir": "/Users/you/.yt2notion-agent/workspace/abc123",
  "video_id": "abc123",
  "title": "Example title",
  "channel": "Example channel",
  "result_path": null,
  "error": null
}
```

Rules:

- `current_step` is the live step in progress, not the last completed step.
- `completed_steps` is append-only during a run.
- `result_path` is the summary markdown path returned by Obsidian storage after success.
- `error` stores the terminal failure message on failure.

### `logs/<job-id>.log`

Append-only text log:

- worker startup
- step transitions
- pipeline verbose output
- final success or failure line

`agent logs <job-id>` prints this file.

## CLI Commands

### `agent init`

Creates the runtime home if missing:

- default `agent.yaml`
- runtime `AGENTS.md`
- `jobs/`, `logs/`, and `workspace/`
- empty `queue.json` if missing

It should be safe to run repeatedly.

### `agent add <url>`

- validate config exists
- create job file with `queued`
- append job id to `queue.json`
- if no live worker exists, spawn a background worker to drain the queue
- print the job id and whether a worker was started

### `agent run --foreground`

Foreground drain command for debugging and development:

- process queued jobs until empty
- stream progress to the current terminal
- do not detach

### `agent status`

Queue summary:

- worker running or idle
- active job id and step if any
- queued job count
- last few job outcomes

### `agent list`

Tabular summary of recent jobs:

- job id
- status
- title or URL
- current step / result
- updated time

### `agent show <job-id>`

Detailed view of one job:

- metadata known so far
- live status
- workspace path
- result path on success
- error on failure

### `agent logs <job-id>`

Print raw log file for that job.

### `agent retry <job-id>`

- only allowed for `failed` jobs
- create a new queued job pointing at the same URL
- do not mutate history of the failed original job

This keeps job history immutable and easy to reason about.

## Worker Design

### Startup

`agent add` autostarts a worker when the queue is non-empty and no live worker exists.

Implementation mechanism:

- use `subprocess.Popen()` to spawn the same CLI with an internal worker entrypoint
- redirect stdout/stderr to the active job log when possible
- use `start_new_session=True` so the worker survives the calling shell

### Internal Worker Command

Use an internal subcommand such as:

```bash
uv run yt2notion agent _worker
```

This command is intentionally undocumented and owned by the queue layer.

### Drain Loop

For each queued job:

1. mark job `starting`
2. pop from queue
3. mark worker active
4. run pipeline
5. mark job `completed` or `failed`
6. clear worker state if queue empty, otherwise continue

### Crash Recovery

On each command invocation:

- if `worker.json` exists but PID is dead, treat worker as stale
- clear `worker.json`
- leave the active job untouched
- if the stale job is still `starting` or `running`, mark it `failed` with a worker-crash message

This is sufficient for MVP. More advanced resume logic is future work.

## Pipeline Integration

The actual media work should still be done by existing pipeline code, not a new pipeline.

### Publishing Path

Use `run_pipeline()` rather than `prepare_content()` so Obsidian writing stays in the existing storage backend path.

Because the product constraint is fixed to Obsidian + summary mode, this publish is expected behavior, not an extra confirmation step.

### Progress Reporting

Add an optional progress callback to pipeline entrypoints. Minimal shape:

```python
PipelineProgress(step: str, event: str, message: str | None = None)
```

Event values:

- `started`
- `completed`
- `failed`
- `skipped`

This callback is invoked at step boundaries inside `prepare_content()` / `run_pipeline()`.

The agent worker uses it to keep `jobs/<job-id>.json` current.

This is preferable to inferring progress from workspace artifacts because it can show the current in-flight step before the artifact is written.

### Metadata Backfill

As soon as download metadata is available, the worker updates the job file with:

- `video_id`
- `title`
- `channel`
- `workspace_dir`

This makes `agent list` and `agent show` useful early in the run.

## Codex Runtime Isolation

The existing `codex_cli` backend currently inherits the current working directory. That is not acceptable for the agent because the repository root `AGENTS.md` is for development, not runtime content processing.

Design change:

- `CodexCLICaller` and `CodexCLIModel` accept an optional working directory
- `create_llm_caller()` and `create_summarizer()` read an optional internal config field for that working directory
- the agent runner sets that value to `<agent_home>`

This keeps normal repo development behavior unchanged while isolating agent runtime behavior cleanly.

## Notifications

MVP notifications are terminal-oriented only.

Required behavior:

- on success, append a clear line to the log and print one line including job id and result path
- on failure, append a clear line to the log and print one line including job id and error summary

Optional small enhancement:

- emit `\a` bell on completion when attached to a terminal

No OS notification integration in MVP.

## Testing Strategy

### Unit Tests

- config loader for `agent.yaml`
- queue state read/write helpers
- worker liveness / stale PID detection
- job state transitions
- retry command semantics
- runtime Codex workdir plumbing

### CLI Tests

- `agent init` creates expected files
- `agent add` creates a queued job and starts worker when idle
- `agent status` renders correct summary for idle and running states
- `agent show` and `agent logs` work for known jobs

### Integration Tests

Mock pipeline execution or patch storage/model layers so tests validate:

- queue drains in order
- success updates `result_path`
- failure updates `error`
- progress callback writes `current_step`

### Verification Standard

Before completion, run targeted tests for the new agent files plus any touched pipeline/model tests, then run `ruff check` on all edited files.

## Files Likely to Change

| File | Change |
|------|--------|
| `src/yt2notion/cli.py` | Add `agent` command group |
| `src/yt2notion/pipeline.py` | Add optional progress callback hooks |
| `src/yt2notion/models/codex_cli.py` | Add optional runtime working directory |
| `src/yt2notion/models/llm.py` | Pass through runtime working directory for Codex caller |
| `src/yt2notion/models/__init__.py` | Pass through runtime working directory for Codex summarizer |
| `src/yt2notion/config.py` | Add internal config mapping support as needed |
| `PROJECT_MAP.md` | Document new CLI entrypoint and any new internal config mapping |
| `handoff.md` | Track design/implementation handoff |
| `tests/test_cli.py` | Add agent CLI tests |
| `tests/test_pipeline.py` | Add progress callback tests if pipeline changes land here |
| `tests/test_codex_cli.py` | Add working-directory plumbing tests |
| `tests/test_agent_*.py` | New queue / worker / config tests |

## Alternatives Considered

### 1. Reuse Root `config.yaml` and Root `AGENTS.md`

Rejected.

- mixes development control plane with runtime control plane
- makes Codex runtime behavior depend on repository instructions
- exposes too much configuration surface to the user

### 2. Pure Foreground Queue Only

Rejected for the first version.

- simpler technically
- but weaker UX because `add` does not feel agent-like

The chosen design keeps file-backed behavior but still autostarts a short-lived worker.

### 3. Persistent Daemon

Rejected.

- adds PID lifecycle complexity and service management
- unnecessary for the current workflow

## Open Questions

These are intentionally left for implementation planning, not product definition:

- exact formatting of `status` / `list` terminal output
- whether `agent add` should accept multiple URLs in one invocation
- whether the worker should reuse `resume` semantics after a partial pipeline failure or simply fail the job
