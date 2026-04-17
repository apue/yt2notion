# Minimal Agent Error Diagnosis

## Goal

Add a minimal diagnosis layer so an AI agent can answer requests like `帮我检查最近一次错误` by following a fixed repo-local workflow:

1. list recent agent jobs,
2. identify the most recent failed job,
3. read that job's metadata and log,
4. map the raw error to a human explanation,
5. tell the user whether retry is likely useful.

This slice is intentionally small. It is not a telemetry system, error platform, or generic observability project.

## Scope

### In Scope

- `agent` workflow only:
  - `uv run yt2notion agent list`
  - `uv run yt2notion agent show <job_id>`
  - `uv run yt2notion agent logs <job_id>`
- One repo-local diagnosis guide document
- One repo-local skill that tells AI exactly how to inspect and explain agent failures
- A minimal failure summary block appended to job logs on failure
- A small catalog of common failure patterns across:
  - config/runtime
  - download/extract
  - ASR
  - Codex/LLM

### Out of Scope

- Generic failure handling for non-agent CLI entrypoints
- Structured error models or telemetry backends
- Dashboard, database, or analytics layer
- Automatic retry policy changes
- Large-scale log format redesign

## User-Facing Behavior

After this slice ships, the intended interaction is:

```text
User: 帮我检查最近一次错误
AI:
1. run `uv run yt2notion agent list`
2. pick the most recent `failed` job id
3. run `uv run yt2notion agent show <job_id>`
4. run `uv run yt2notion agent logs <job_id>`
5. read `docs/agent-error-guide.md`
6. answer in plain Chinese:
   - failure step
   - direct cause
   - human explanation
   - whether retry is useful
   - what to inspect next if retry is not enough
```

The AI should not guess based on one line of stderr. It must follow the command sequence above.

If the observed failure does not match any known pattern in the guide, the AI must say that clearly instead of forcing a known diagnosis.

## Deliverables

### 1. Diagnosis Guide

Create:

```text
docs/agent-error-guide.md
```

This document is the only diagnosis reference for the first version.

It must contain:

- The exact command workflow for inspecting the latest failed job
- Where job records and logs live under `~/.yt2notion-agent/`
- How to interpret `agent list`, `agent show`, and `agent logs`
- A compact error catalog table with these columns:
  - `pattern`
  - `step`
  - `substep`
  - `meaning`
  - `retry advice`
  - `next action`

The document must stay practical. It should explain only current recurring failures that AI is expected to identify.

It must also contain a short `Unknown Error Handling` section that explains what to do when no existing pattern matches:

- keep the raw error phrase,
- identify the step from `agent show` and `agent logs`,
- report the case as `unknown`,
- recommend whether a new guide entry or a new log hint is needed.

Initial catalog coverage must include at least:

- `SSL: UNEXPECTED_EOF_WHILE_READING`
- `HTTP Error 403: Forbidden`
- `yt-dlp not found`
- `No subtitles and no ASR endpoint configured`
- ASR request 5xx / unreachable server
- Codex CLI non-zero exit
- missing Codex profile or model configuration

### 2. Repo-Local Diagnosis Skill

Create:

```text
.agents/skills/agent-error-diagnosis/SKILL.md
```

The skill exists to enforce procedure, not to carry domain theory.

The skill must instruct AI to:

1. run `uv run yt2notion agent list`
2. choose the latest failed job unless the user names a specific `job_id`
3. run `uv run yt2notion agent show <job_id>`
4. run `uv run yt2notion agent logs <job_id>`
5. consult `docs/agent-error-guide.md`
6. return a fixed diagnosis summary

The summary format must be:

- `失败任务`
- `失败节点`
- `直接原因`
- `人话解释`
- `是否建议 retry`
- `下一步建议`

The skill should also tell AI:

- do not stop after reading `agent list`
- do not answer from memory
- prefer quoting the observed error phrase from the log before translating it
- if no guide pattern matches, explicitly report `unknown` and recommend updating the guide or log hint logic

### 3. Failure Summary Block in Job Logs

Append a minimal summary block to the end of each failed agent job log.

Required shape:

```text
=== FAILURE SUMMARY ===
step: <pipeline-step>
substep: <more specific location or ->
hint: <short diagnosis tag or ->
retry: <safe|limited|no|unknown>
=== END FAILURE SUMMARY ===
```

Rules:

- This is a convenience hint, not a replacement for the raw log
- `step` must use the existing pipeline step names when known
- `substep` may be `metadata`, `audio_download`, `subtitle_download`, `asr_request`, `codex_exec`, etc.
- `hint` must be a short stable tag, not a full sentence
- `retry` is a human/AI hint only; it does not trigger automatic retries

If the code cannot classify a failure confidently, it must still emit:

```text
hint: unknown
retry: unknown
```

This fallback is required so new failures can still be diagnosed and later added to the guide without changing the overall workflow.

## Classification Rules

The first version should use simple string-pattern classification near the agent failure logging path.

That classifier must:

- inspect the final exception string,
- optionally inspect the current step,
- emit the failure summary block,
- stay small and explicit.

The first version should not introduce a new global exception hierarchy for the whole pipeline.

When a newly observed failure repeats and is useful to distinguish, the follow-up change should be:

1. add or refine the log hint pattern in the agent failure path,
2. add a corresponding entry to `docs/agent-error-guide.md`,
3. keep the skill workflow unchanged.

This keeps the maintenance loop simple: new issue -> improve hint if useful -> update guide.

## Architecture

### Existing Sources of Truth

- job state: `~/.yt2notion-agent/jobs/<job_id>.json`
- job log: `~/.yt2notion-agent/logs/<job_id>.log`
- runtime guide for AI: `.agents/skills/agent-error-diagnosis/SKILL.md`
- diagnosis reference: `docs/agent-error-guide.md`

### Minimal Code Placement

Implementation should stay close to current agent failure handling:

- detect and append the failure summary block in `src/yt2notion/agent_worker.py`
- keep pattern matching local to the agent failure path
- do not refactor unrelated pipeline code in this slice

## Migration Slices

### Slice 1: Guide

- Write `docs/agent-error-guide.md`
- Cover the initial recurring failures already seen in this repo

### Slice 2: Skill

- Add `.agents/skills/agent-error-diagnosis/SKILL.md`
- Ensure it points to the exact commands and guide document

### Slice 3: Failure Summary

- Append the minimal failure summary block to failed job logs
- Add tests for at least:
  - 403-style extract failure
  - SSL EOF extract failure
  - unknown failure fallback

### Slice 4: Unknown Error Update Loop

- Document how maintainers extend the guide for a newly seen failure
- Ensure `unknown` remains a valid first-class outcome rather than a missing case

## Validation Criteria

This slice is complete when all of the following are true:

- An AI following the skill can locate the latest failed job without extra user guidance
- The guide document is sufficient to explain the known recurring failures in plain Chinese
- Failed job logs now end with a `FAILURE SUMMARY` block
- At least one test covers summary emission for known failure patterns
- Unknown failures still produce a summary block with `unknown` values instead of omitting the block
- The guide tells AI what to say when the error is new and not yet cataloged

## Risks

- If the guide and log hint taxonomy drift apart, AI diagnoses will become inconsistent
- If the skill is too vague, AI will skip steps and answer from partial evidence
- If the summary tags become too detailed, this slice will slowly turn into an error platform
- If unknown errors are not captured explicitly, AI will overfit them into the wrong known category

The implementation must bias toward simple tags and guide-based interpretation.
