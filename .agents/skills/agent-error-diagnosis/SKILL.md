---
name: agent-error-diagnosis
description: Use when diagnosing a recent yt2notion agent failure, reading agent list/show/logs, or translating a failed job into a plain Chinese explanation.
---

# Agent Error Diagnosis

## Required Workflow

When the user asks to check a recent agent failure:

1. Run `uv run yt2notion agent list`
2. Choose the latest `failed` job unless the user gave a specific `job_id`
3. Run `uv run yt2notion agent show <job_id>`
4. Run `uv run yt2notion agent logs <job_id>`
5. Read `docs/agent-error-guide.md`
6. Answer only with the fixed diagnosis summary below

Use the observed error phrase from the log before translating it. Do not guess from memory or from `agent list` alone.

## Do Not

- Stop after `agent list`
- Answer from memory
- Modify code, logs, or docs during diagnosis
- Force a known diagnosis when the log does not match the guide

If the log does not match any known pattern, return `unknown` explicitly and recommend updating the guide or the log hint logic later.

## Unknown Handling

When the failure is not covered by `docs/agent-error-guide.md`:

- Keep the raw error phrase
- Use `agent show` and `agent logs` to identify the failure step
- Report `unknown` instead of inventing a match
- Recommend adding a new guide entry or a new log hint pattern

## Output Format

Return the diagnosis in this exact order and with these labels:

- 失败任务：
- 失败节点：
- 直接原因：
- 人话解释：
- 是否建议 retry：
- 下一步建议：
