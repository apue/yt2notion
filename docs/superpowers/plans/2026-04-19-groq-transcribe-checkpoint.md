# Groq Transcribe Checkpoint Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add chunk-level transcription checkpoints with Groq hourly wait handling and daily-limit remote fallback for audio jobs.

**Architecture:** Extend Groq error classification, persist chunk plan and state in the workspace, and teach the pipeline to resume pending chunks and wait through hourly limits in-process. Keep subtitle flows and queue topology unchanged.

**Tech Stack:** Python 3.11, pytest, Typer CLI, JSON workspace artifacts

---

## File Structure

- Modify: `src/yt2notion/transcribe/errors.py`
  - Add explicit hourly and daily quota exceptions.
- Modify: `src/yt2notion/transcribe/groq.py`
  - Parse Groq `429` responses into hourly or daily exceptions and carry retry timing.
- Modify: `src/yt2notion/workspace.py`
  - Persist transcribe plan, state, and per-chunk JSON artifacts.
- Modify: `src/yt2notion/pipeline.py`
  - Orchestrate chunk planning, checkpoint writes, hourly waiting, and daily remote switching.
- Modify: `tests/test_transcribe_groq.py`
  - Cover new Groq quota classification behavior without network calls.
- Modify: `tests/test_workspace.py`
  - Cover plan/state/chunk artifact round-trips and cleanup behavior.
- Modify: `tests/test_pipeline.py`
  - Cover checkpoint resume, hourly wait continuation, and daily remote switch behavior.
- Modify: `PROJECT_MAP.md`
  - Update canonical pipeline and artifact contracts.
- Modify: `README.md`
  - Document the Groq-first checkpoint behavior.
- Modify: `config.example.yaml`
  - Document Groq-first fallback semantics.

### Task 1: Groq Quota Error Classification

**Files:**
- Modify: `src/yt2notion/transcribe/errors.py`
- Modify: `src/yt2notion/transcribe/groq.py`
- Test: `tests/test_transcribe_groq.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_429_with_retry_after_raises_hourly_limit(tmp_path, monkeypatch):
    ...
    with pytest.raises(TranscriptionHourlyLimitError) as exc:
        GroqTranscriber(api_key="k").transcribe(audio)
    assert exc.value.retry_after_seconds == 120


def test_429_daily_limit_message_raises_daily_limit(tmp_path, monkeypatch):
    ...
    with pytest.raises(TranscriptionDailyLimitError):
        GroqTranscriber(api_key="k").transcribe(audio)
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_transcribe_groq.py -q`
Expected: FAIL because the new exception classes and retry parsing do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
class TranscriptionHourlyLimitError(TranscriptionError):
    def __init__(self, message: str, *, retry_after_seconds: int) -> None:
        super().__init__(message)
        self.retry_after_seconds = retry_after_seconds


class TranscriptionDailyLimitError(TranscriptionError):
    pass
```

```python
if code == 429:
    retry_after = _parse_retry_after_seconds(e.response)
    if _looks_like_daily_quota_error(e.response):
        raise TranscriptionDailyLimitError(...)
    raise TranscriptionHourlyLimitError(..., retry_after_seconds=retry_after) from e
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_transcribe_groq.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/transcribe/errors.py src/yt2notion/transcribe/groq.py tests/test_transcribe_groq.py
git commit -m "feat: classify groq hourly and daily quota limits"
```

### Task 2: Workspace Checkpoint Artifacts

**Files:**
- Modify: `src/yt2notion/workspace.py`
- Test: `tests/test_workspace.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_transcribe_plan_state_and_chunk_roundtrip(tmp_path):
    ...
    ws.save_transcribe_plan(plan)
    ws.save_transcribe_state(state)
    ws.save_transcribe_chunk_result("chunk-001", chunk_entries)
    assert ws.load_transcribe_plan() == plan
    assert ws.load_transcribe_state() == state
    assert ws.load_transcribe_chunk_result("chunk-001") == chunk_entries


def test_discard_transcribe_artifacts_removes_checkpoint_files(tmp_path):
    ...
    ws.discard_transcribe_artifacts(audio_path=audio)
    assert ws.load_transcribe_plan() is None
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_workspace.py -q`
Expected: FAIL because the new workspace helpers do not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def save_transcribe_plan(self, plan: dict) -> None:
    self._write_json("transcribe_plan.json", plan)


def save_transcribe_chunk_result(self, chunk_id: str, entries: list[dict]) -> None:
    path = self.dir / "transcribe_chunks"
    path.mkdir(exist_ok=True)
    self._write_json(f"transcribe_chunks/{chunk_id}.json", entries)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_workspace.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/workspace.py tests/test_workspace.py
git commit -m "feat: persist transcribe checkpoint artifacts"
```

### Task 3: Pipeline Chunk Resume and Fallback Flow

**Files:**
- Modify: `src/yt2notion/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing tests**

```python
def test_transcribe_audio_waits_and_resumes_after_hourly_limit(...):
    ...
    assert sleep_calls == [60, 60]
    assert result[0]["text"] == "chunk one chunk two"


def test_transcribe_audio_switches_remaining_chunks_to_remote_after_daily_limit(...):
    ...
    assert remote.transcribe.call_count == 2
    assert ws.asr_fallback_used() is True
```

- [ ] **Step 2: Run tests to verify failure**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: FAIL because the pipeline does not yet persist chunk state or wait through hourly limits.

- [ ] **Step 3: Write minimal implementation**

```python
def _wait_until_retryable_time(next_attempt_at: datetime, *, verbose: bool) -> None:
    while True:
        remaining = (next_attempt_at - _now()).total_seconds()
        if remaining <= 0:
            return
        time.sleep(min(remaining, 60))
```

```python
except TranscriptionHourlyLimitError as exc:
    state["status"] = "waiting_ash"
    state["next_attempt_at"] = ...
    ws.save_transcribe_state(state)
    _wait_until_retryable_time(...)
    continue

except TranscriptionDailyLimitError:
    state["job_mode"] = "remote_remaining"
    _switch_remaining_chunks_to_remote(...)
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/test_pipeline.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/yt2notion/pipeline.py tests/test_pipeline.py
git commit -m "feat: resume groq transcription across chunk checkpoints"
```

### Task 4: Canonical Docs and User-Facing Config Notes

**Files:**
- Modify: `PROJECT_MAP.md`
- Modify: `README.md`
- Modify: `config.example.yaml`
- Modify: `handoff.md`

- [ ] **Step 1: Write the failing documentation diff**

```text
PROJECT_MAP.md must describe:
- transcribe_plan.json
- transcribe_state.json
- transcribe_chunks/<chunk_id>.json
- ASH wait semantics
- ASD remaining-chunk remote fallback semantics
```

- [ ] **Step 2: Verify missing details before editing**

Run: `rg -n "transcribe_plan|waiting_ash|TranscriptionHourlyLimitError|ASD" PROJECT_MAP.md README.md config.example.yaml`
Expected: no matches before the docs update.

- [ ] **Step 3: Write the minimal documentation updates**

```text
- `ASH` waits through the hourly window and resumes the same pending chunk from checkpointed state.
- `ASD` switches the current failed chunk and all remaining pending chunks to `remote`.
```

- [ ] **Step 4: Run targeted checks**

Run: `python - <<'PY'\nfrom pathlib import Path\nfor path in [Path('PROJECT_MAP.md'), Path('README.md'), Path('config.example.yaml'), Path('handoff.md')]:\n    assert path.read_text(encoding='utf-8')\nprint('ok')\nPY`
Expected: `ok`

- [ ] **Step 5: Commit**

```bash
git add PROJECT_MAP.md README.md config.example.yaml handoff.md docs/superpowers/specs/2026-04-19-groq-transcribe-checkpoint-design.md docs/superpowers/plans/2026-04-19-groq-transcribe-checkpoint.md
git commit -m "docs: document groq transcription checkpoint design"
```
