# Groq ASR Primary + Local Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Groq the default ASR backend, keep the existing remote Qwen service as per-job fallback, and harden the local ASR restart path so fallback is actually reliable in real runs.

**Architecture:** Keep the current pipeline contract intact: subtitles still bypass ASR, transcription still writes `transcripts.json`, and fallback only reruns the transcribe step. Extend the ASR factory/config layer to support `groq` + `fallback_backend`, route retryable Groq failures to remote, and fix the remote restart script so it does not report false-positive health while the old listener still owns the port.

**Tech Stack:** Python, `httpx`, existing `yt2notion.retry`, FastAPI-based remote ASR service, `ffmpeg`, shell restart script, pytest, ruff.

---

## Current State To Preserve

- `src/yt2notion/transcribe/groq.py` already exists and works on real `.mp3` and `.m4a` samples, but still hardcodes multipart MIME as `audio/mpeg`.
- `src/yt2notion/config.py` already contains `groq` defaults and `fallback_backend` validation.
- Benchmark on 6 real 10-minute clips showed Groq is materially faster and textually preferred over local ASR, so the remaining work is productization, not feasibility.
- The current restart path in `scripts/asr/restart_remote_asr.sh` is racy: it can kill the old process, start a new one before port `8930` is actually free, and declare success while the old listener briefly satisfies health checks.

## Decisions Locked

- Primary backend becomes `groq`.
- Fallback backend stays `remote`.
- Fallback triggers only on Groq `429` and `5xx`.
- `400/401/403` from Groq fail directly with no fallback.
- `agent.yaml` does not grow Groq-specific fields; repo `config.yaml` remains the source of truth for `extract.asr.*`.
- Direct `.m4a` upload is supported; no pre-conversion step is required for Groq.
- MIME handling must be based on file suffix, not hardcoded to `audio/mpeg`.

## File Map

- `src/yt2notion/transcribe/base.py`
  Transcriber protocol and shared type surface.
- `src/yt2notion/transcribe/errors.py`
  Shared transcription error hierarchy used by Groq, remote, and pipeline fallback control flow.
- `src/yt2notion/transcribe/groq.py`
  Groq backend, multipart upload construction, MIME detection, retry/status mapping.
- `src/yt2notion/transcribe/remote.py`
  Remote backend alignment with shared errors/protocol.
- `src/yt2notion/transcribe/__init__.py`
  Primary/fallback factory wiring.
- `src/yt2notion/pipeline.py`
  Transcribe-step fallback routing and upload-size-aware chunking behavior.
- `src/yt2notion/workspace.py`
  Transcribe artifact discard + fallback marker persistence.
- `src/yt2notion/agent_worker.py`
  Persist `asr_fallback_used` into job records.
- `src/yt2notion/cli.py`
  Surface fallback usage in `agent show`.
- `scripts/asr/restart_remote_asr.sh`
  Remote ASR restart sequencing and readiness checks.
- `config.example.yaml`
  Example `groq` + `fallback_backend` configuration.
- `PROJECT_MAP.md`
  Canonical pipeline/config/factory truth.
- `docs/operations/asr-service.md`
  Operational expectations for remote ASR restart behavior.
- `tests/test_transcribe_base.py`
- `tests/test_transcribe_groq.py`
- `tests/test_transcribe_factory.py`
- `tests/test_pipeline.py`
- `tests/test_workspace.py`
- `tests/test_agent_worker.py`
- `tests/test_cli.py`
- `tests/test_config.py`
  Test coverage for the above.

### Task 1: Finish Shared ASR Surface

**Files:**
- Create: `src/yt2notion/transcribe/base.py`
- Create: `src/yt2notion/transcribe/errors.py`
- Modify: `src/yt2notion/transcribe/remote.py`
- Test: `tests/test_transcribe_base.py`

- [ ] Add `Transcriber` protocol with `max_upload_bytes` and `transcribe(...) -> list[SubtitleEntry]`.
- [ ] Move shared exceptions into `transcribe/errors.py`:
  `TranscriptionError`, `TranscriptionQuotaError`, `TranscriptionServerError`.
- [ ] Update `RemoteTranscriber` to import shared errors and expose `max_upload_bytes: int | None = None`.
- [ ] Add tests that verify import paths, inheritance, and `RemoteTranscriber.max_upload_bytes is None`.
- [ ] Run:
  `uv run pytest tests/test_transcribe_base.py -q`
- [ ] Run:
  `uv run ruff check src/yt2notion/transcribe/base.py src/yt2notion/transcribe/errors.py src/yt2notion/transcribe/remote.py tests/test_transcribe_base.py`

### Task 2: Make Groq Backend Production-Ready

**Files:**
- Modify: `src/yt2notion/transcribe/groq.py`
- Test: `tests/test_transcribe_groq.py`

- [ ] Keep existing retry/status mapping, but replace hardcoded multipart MIME with suffix-based detection.
- [ ] Support at least:
  `.mp3 -> audio/mpeg`
  `.m4a -> audio/mp4`
  `.mp4 -> audio/mp4`
  `.wav -> audio/wav`
  `.ogg -> audio/ogg`
  `.webm -> audio/webm`
  Unknown suffix -> omit MIME or fall back to `application/octet-stream`.
- [ ] Preserve pre-flight size rejection via `max_upload_bytes`.
- [ ] Add tests for `.m4a` and `.mp3` multipart payload construction, plus unknown-suffix fallback behavior.
- [ ] Keep real behavior aligned with benchmark finding: direct `.m4a` upload must remain supported.
- [ ] Run:
  `uv run pytest tests/test_transcribe_groq.py -q`
- [ ] Run:
  `uv run ruff check src/yt2notion/transcribe/groq.py tests/test_transcribe_groq.py`

### Task 3: Complete Primary/Fallback Wiring

**Files:**
- Modify: `src/yt2notion/transcribe/__init__.py`
- Modify: `src/yt2notion/pipeline.py`
- Modify: `src/yt2notion/workspace.py`
- Modify: `src/yt2notion/agent_worker.py`
- Modify: `src/yt2notion/cli.py`
- Test: `tests/test_transcribe_factory.py`
- Test: `tests/test_pipeline.py`
- Test: `tests/test_workspace.py`
- Test: `tests/test_agent_worker.py`
- Test: `tests/test_cli.py`

- [ ] Extend factory code so `create_transcriber(config)` returns the primary backend and `create_fallback_transcriber(config)` returns the optional fallback backend.
- [ ] Use `GROQ_API_KEY` env fallback when config key is empty.
- [ ] Update `_step_transcribe()` in `pipeline.py` so:
  subtitles still bypass ASR;
  Groq is primary when configured;
  only `TranscriptionQuotaError` / `TranscriptionServerError` trigger fallback;
  fallback reruns only the transcribe step after discarding `transcripts.json` and split-audio dirs.
- [ ] Add workspace methods to discard transcribe artifacts and persist an `asr_fallback_used` marker.
- [ ] Persist `asr_fallback_used` into agent job records and expose it in `agent show`.
- [ ] Preserve old behavior bit-for-bit when config remains `backend: remote` with no fallback.
- [ ] Run:
  `uv run pytest tests/test_transcribe_factory.py tests/test_pipeline.py tests/test_workspace.py tests/test_agent_worker.py tests/test_cli.py -q`
- [ ] Run:
  `uv run ruff check src/yt2notion/transcribe/__init__.py src/yt2notion/pipeline.py src/yt2notion/workspace.py src/yt2notion/agent_worker.py src/yt2notion/cli.py tests/test_transcribe_factory.py tests/test_pipeline.py tests/test_workspace.py tests/test_agent_worker.py tests/test_cli.py`

### Task 4: Make Upload Splitting Respect Groq Byte Limits

**Files:**
- Modify: `src/yt2notion/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] Reuse chapter segmentation when present.
- [ ] If a per-segment file exceeds `transcriber.max_upload_bytes`, subdivide that segment by duration until child chunks fit the byte budget.
- [ ] In no-chapter mode, fast-path a single upload when the full audio file is already under the byte limit.
- [ ] Otherwise compute chunk duration from both configured chunk size and byte budget:
  `duration * (max_bytes / file_size) * 0.9`, floor at 30 seconds.
- [ ] Keep timestamp rebasing correct when concatenating child chunk transcripts.
- [ ] Add tests for:
  small full-audio fast path,
  oversized segment subdivision,
  quota/server-error fallback path,
  non-fallback error propagation.
- [ ] Run:
  `uv run pytest tests/test_pipeline.py -q`

### Task 5: Harden Remote ASR Restart Semantics

**Files:**
- Modify: `scripts/asr/restart_remote_asr.sh`
- Modify: `docs/operations/asr-service.md`

- [ ] Change the restart script so it does not start a new server until the old `server_mlx.py` process is gone and port `8930` is no longer listening.
- [ ] Keep the remote `PATH` bootstrap and `ffmpeg` preflight.
- [ ] After startup, health checks must prove the new process is really serving; the script must not succeed solely because an old listener answered.
- [ ] Preserve current CLI surface:
  `scripts/asr/restart_remote_asr.sh <asr_host>`
- [ ] Document the benchmark-discovered failure mode in `docs/operations/asr-service.md`: false-positive restart success caused by bind race / stale listener.
- [ ] Add a manual verification block to the docs:
  1. run restart script
  2. confirm remote `lsof -iTCP:8930 -sTCP:LISTEN`
  3. confirm `curl http://<host>:8930/health`
  4. confirm one real `/transcribe` request succeeds

### Task 6: Sync Config Examples And Canonical Docs

**Files:**
- Modify: `config.example.yaml`
- Modify: `PROJECT_MAP.md`
- Modify: `README.md`
- Modify: `handoff.md`

- [ ] Update `config.example.yaml` to show the new recommended path:
  `extract.asr.backend: groq`
  `extract.asr.fallback_backend: remote`
  `extract.asr.groq.*`
  existing remote restart settings retained for fallback.
- [ ] Do not put any real API key in repo docs or examples.
- [ ] Update `PROJECT_MAP.md` so canonical facts match the new implementation:
  `create_transcriber()` supports `groq` and `remote`;
  `create_fallback_transcriber()` exists;
  `extract.asr.groq.*` maps to `transcribe/groq.py`;
  transcribe branch rule now includes Groq-primary fallback behavior;
  agent config preservation note explicitly includes `groq` and `fallback_backend`.
- [ ] Update `README.md` with a short ASR backend note and fallback behavior summary.
- [ ] Update `handoff.md` with a new task card for this work before implementation starts.

## Validation Commands

Run the smallest relevant subsets during each task, then finish with:

```bash
uv run pytest tests/test_config.py tests/test_transcribe_base.py tests/test_transcribe_groq.py tests/test_transcribe_factory.py tests/test_workspace.py tests/test_pipeline.py tests/test_agent_worker.py tests/test_cli.py -q
uv run ruff check src/yt2notion/ tests/
uv run ruff format --check src/ tests/
```

## Review Checklist

- Groq `.m4a` upload path works without pre-conversion.
- Old `backend: remote` configs still behave the same.
- Fallback only triggers on Groq `429` / `5xx`.
- Remote restart script no longer reports success while a stale listener still owns `8930`.
- `PROJECT_MAP.md` is updated before any summary docs drift away from implementation truth.

## Out Of Scope

- SQLite state layer
- Cross-job sticky fallback or cooldown
- Per-language routing such as `zh -> remote` / `en -> groq`
- Streaming transcription
- Notion/publish-path changes
- Replacing the remote ASR service implementation itself
