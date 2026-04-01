# Pipeline Resilience for Unattended Execution

## Goal

Make `yt2notion process <url>` reliably run to completion without human interaction — from URL to Obsidian note (summary + transcript). When a step fails after retries, mark the failure structurally so the user knows what happened.

## Scope

Pipeline-level changes only. No changes to triggering mechanism (cron, file watch, etc.) — that's a separate project.

## Current Problems

1. **Interactive confirmation blocks unattended runs.** `typer.confirm("Publish to storage?")` returns False in non-interactive mode → pipeline exits before publish and deferred review.
2. **LLM calls have zero retry.** `ClaudeCodeCaller.call()` fails on transient errors (timeout, rate limit, empty response) and the exception kills the pipeline.
3. **ASR calls have zero retry.** `RemoteTranscriber.transcribe()` fails on network errors / service restarts with no retry.
4. **Deferred review silently degrades.** Catches all exceptions, falls back to unreviewed transcript. User never knows quality was reduced.
5. **No structured failure reporting.** Pipeline crashes leave only stderr. No machine-readable record of what failed.

## Design

### 1. Remove Interactive Confirmation

Remove the `typer.confirm()` block entirely from `pipeline.py:171-179`. The `--no-confirm` CLI flag becomes unnecessary but can stay for backwards compatibility.

Rationale: `--dry-run` already covers "preview without publishing". The confirm prompt serves no purpose in the target workflow and actively blocks unattended execution.

### 2. Retry in `ClaudeCodeCaller.call()`

Add retry logic **inside** the `call()` method in `models/llm.py:28-50`.

**Retryable errors:**
- `subprocess.CalledProcessError` (non-zero exit from `claude -p`)
- Empty or whitespace-only output (LLM returned nothing)
- `subprocess.TimeoutExpired` (need to add a timeout to `subprocess.run`)

**Non-retryable errors:**
- `FileNotFoundError` (`claude` not on PATH — will never succeed)
- `json.JSONDecodeError` on the response — this is a prompt/output-format issue, not transient

**Parameters:**
- Max retries: 3
- Backoff: exponential with base 5s → 5s, 15s, 45s
- Timeout per call: 120s (add `timeout=120` to `subprocess.run`)

**Logging:** Each retry prints to stderr: `Retry {n}/3 for claude -p (error: {brief_msg}), waiting {delay}s...`

### 3. Retry in `RemoteTranscriber.transcribe()`

Add retry logic **inside** the `transcribe()` method in `transcribe/remote.py:23-54`.

**Retryable errors:**
- `httpx.ConnectError`, `httpx.TimeoutException` (network-level)
- HTTP 5xx responses (server error)

**Non-retryable errors:**
- HTTP 4xx responses (client error — bad request, not found)
- JSON decode errors on response (server returned garbage)

**Parameters:**
- Max retries: 3
- Backoff: exponential with base 10s → 10s, 30s, 90s (ASR is slower to recover)
- Timeout: already configurable via `self.timeout` (default 1800s)

**Logging:** Same pattern as LLM caller.

### 4. Retry in `ClaudeCodeModel._call_claude()`

`ClaudeCodeModel` (the Summarizer implementation in `models/claude_code.py`) has its own `subprocess.run` call to `claude -p`, separate from `ClaudeCodeCaller`. Apply the same retry pattern using the shared `retry()` helper.

Same retryable/non-retryable classification as section 2. Same parameters (3 retries, 5s base backoff, 120s timeout).

### 5. Pipeline Top-Level Failure Handling

Add failure handling **inside** `run_pipeline()` in `pipeline.py`. The function already has access to the `Workspace` object and knows which step is executing.

On unrecoverable failure (wrap the body after workspace creation in try/except):
- Write `workspace/<video_id>/failed.json` via `ws.save_failure()`:
  ```json
  {
    "url": "https://...",
    "step": "extract",
    "error": "claude CLI failed (exit 1): rate limit exceeded",
    "timestamp": "2026-04-01T22:30:00+08:00",
    "retries_exhausted": true
  }
  ```
- Re-raise the exception (CLI layer still handles exit code)

On success (after publish completes):
- Call `ws.clear_failure()` to delete any `failed.json` from a previous failed run

The `step` field is set by tracking a `current_step` variable that updates as the pipeline progresses through each step.

### 6. Deferred Review: Retry + Explicit Degradation

The deferred review in `pipeline.py:672-725` currently has a catch-all that silently falls back. Change to:

1. **Remove the try/catch.** Let the retry-enabled `ClaudeCodeCaller` handle transient errors internally.
2. **Add a targeted catch** only for the case where all retries are exhausted. In that case:
   - Use unreviewed transcript (same as current fallback)
   - Add a note at the top of the transcript output: `> ⚠️ 逐字稿未经校对（校对步骤失败）`
   - Log a warning to stderr
3. The transcript sub-page is still created (partial delivery is better than no delivery).

### 7. Implementation Notes

**Retry utility:** Create a small `_retry` helper function rather than duplicating retry logic. Place it in a new `src/yt2notion/retry.py` module:

```python
def retry(fn, *, max_retries=3, base_delay=5.0, retryable=(Exception,)):
    """Call fn(), retrying on retryable exceptions with exponential backoff."""
```

`ClaudeCodeCaller`, `RemoteTranscriber`, and `ClaudeCodeModel` (Summarizer) all use this helper internally. It is not part of any protocol — it's an implementation detail.

**No config for retry parameters.** Hardcode the retry counts and delays. These are operational constants, not user preferences. If they need tuning, we change the code.

## Files Changed

| File | Change |
|------|--------|
| `src/yt2notion/retry.py` | **New.** Retry helper with exponential backoff |
| `src/yt2notion/models/llm.py` | Add retry + timeout to `ClaudeCodeCaller.call()` |
| `src/yt2notion/models/claude_code.py` | Add retry + timeout to `ClaudeCodeModel._call_claude()` |
| `src/yt2notion/transcribe/remote.py` | Add retry to `RemoteTranscriber.transcribe()` |
| `src/yt2notion/pipeline.py` | Remove `typer.confirm()` block; add failure tracking; fix deferred review |
| `src/yt2notion/workspace.py` | Add `save_failure()` / `clear_failure()` methods |
| `tests/test_retry.py` | **New.** Tests for retry helper |
| `tests/test_llm_retry.py` | **New.** Tests for ClaudeCodeCaller and ClaudeCodeModel retry |
| `tests/test_transcriber_retry.py` | **New.** Tests for RemoteTranscriber retry behavior |
| `tests/test_pipeline.py` | Update: no more confirm prompt; test failure tracking |

## Out of Scope

- Triggering mechanism (cron, file watch, iCloud integration)
- Retry for `yt-dlp` download failures (already reasonably robust)
- Notification on failure (push notification, email, etc.)
