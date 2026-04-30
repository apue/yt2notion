# Groq Transcribe Checkpoint Design

**Goal**

Implement resumable audio transcription that maximizes `Groq` usage, waits through hourly limits, and only falls back to `remote` after daily quota exhaustion.

**Non-Goals**

- No new ASR backend.
- No queue split or new scheduler.
- No database or concurrent state store.
- No live tests against Groq, remote ASR, or any LLM service.

**Execution Scope**

- Audio transcription only. Subtitle-derived transcripts keep the current flow.
- The checkpoint model must work for both `agent` runs and direct `process` / `prepare` CLI runs.
- The first implementation keeps the current single worker, single job execution model.

**Approved Behavior**

1. Audio transcription is executed as an explicit chunk plan, not as one opaque step.
2. Every successful chunk is persisted immediately and is never recomputed unless the user deletes workspace artifacts manually.
3. `Groq` hourly limit (`ASH`) does not trigger fallback.
4. `Groq` daily limit (`ASD`) switches the current failed chunk and all remaining pending chunks of the same job to `remote`.
5. Final `transcripts.json` is written only after all chunks are completed.
6. The waiting behavior for `ASH` is handled by the current running process through persisted state plus short-interval sleep loops.

**Architecture**

The implementation adds explicit chunk planning and state artifacts under the workspace. `GroqTranscriber` becomes responsible for distinguishing hourly and daily quota failures. The pipeline becomes responsible for chunk lifecycle, waiting through hourly limits, and switching the remaining work to `remote` after daily exhaustion.

**Workspace Artifacts**

- `transcribe_plan.json`
  - Immutable plan for the current audio transcription run.
  - Each item stores:
    - `chunk_id`
    - `title`
    - `start_seconds`
    - `end_seconds`
    - `audio_relpath`
    - `preferred_backend`
- `transcribe_state.json`
  - Mutable execution state.
  - Top-level fields:
    - `version`
    - `job_mode` with values `groq` or `remote_remaining`
    - `status` with values `running`, `waiting_ash`, `completed`
    - `next_attempt_at`
    - `last_error`
    - `defer_reason`
    - `ash_defer_count`
    - `chunks`
  - Each chunk item stores:
    - `chunk_id`
    - `status` with values `pending`, `completed_groq`, `completed_remote`
    - `backend_used`
    - `result_relpath`
    - `attempts`
    - `updated_at`
- `transcribe_chunks/<chunk_id>.json`
  - Persisted chunk result with rebased timestamps on the original media timeline.
- `transcripts.json`
  - Final merged artifact only after all chunks complete.

**Error Model**

Replace the current single quota class with explicit quota semantics:

- `TranscriptionHourlyLimitError`
  - Carries `retry_after_seconds`
  - Means the pipeline should wait and retry the same pending chunk later
- `TranscriptionDailyLimitError`
  - Means the pipeline should switch all remaining pending work for the current job to `remote`

`GroqTranscriber` must parse `retry-after` when available. If a `429` cannot be classified beyond “quota limited”, the implementation should treat it as hourly and use a conservative default wait duration.

**Pipeline Flow**

For audio transcription:

1. Build or load `transcribe_plan.json`.
2. Build or load `transcribe_state.json`.
3. Skip any chunk already marked `completed_groq` or `completed_remote`.
4. For each pending chunk:
   - transcribe with its current preferred backend
   - persist `transcribe_chunks/<chunk_id>.json`
   - persist updated `transcribe_state.json`
5. If all chunks complete:
   - merge chunk result files in chunk order
   - write final `transcripts.json`
   - mark `transcribe_state.json` as completed

**ASH Handling**

When `Groq` raises `TranscriptionHourlyLimitError`:

- Keep the current chunk in `pending`
- Persist `next_attempt_at`
- Persist `defer_reason = "ash"`
- Increment `ash_defer_count`
- Enter a short-interval wait loop in the current process
- Re-read time until `next_attempt_at`, then retry the same chunk

The wait loop must not depend on in-memory-only state. If the process exits, the next run must be able to continue from the persisted checkpoint data.

**ASD Handling**

When `Groq` raises `TranscriptionDailyLimitError`:

- Keep completed Groq chunks unchanged
- Mark the current failed chunk and every remaining pending chunk as `preferred_backend = "remote"`
- Switch job mode to `remote_remaining`
- Continue the current run without waiting
- Mark workspace fallback usage through the existing fallback marker

**Resume Behavior**

- `agent` and direct CLI commands share the same checkpoint artifacts.
- Direct CLI resume via `--resume` and `--from transcribe` remains valid and should continue from the persisted chunk state.
- Rerunning from an earlier step than `transcribe` discards the previous transcribe checkpoint set before starting a new ASR pass.
- The current running process also waits through hourly limits by default, so direct CLI runs do not require manual re-entry for the first implementation.

**Validation Criteria**

- Successful chunks survive process interruption.
- Hourly quota waits do not wipe finished chunk results.
- Daily quota switch affects only the remaining pending chunks.
- Subtitle paths remain unchanged.
- Existing remote-only behavior remains unchanged.
- No test touches Groq, remote ASR, or any LLM service.

**Primary Files**

- `src/yt2notion/transcribe/errors.py`
- `src/yt2notion/transcribe/groq.py`
- `src/yt2notion/workspace.py`
- `src/yt2notion/pipeline.py`
- `tests/test_transcribe_groq.py`
- `tests/test_workspace.py`
- `tests/test_pipeline.py`
- `PROJECT_MAP.md`
- `README.md`
- `config.example.yaml`
