# Bundle-Only Transcript Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `yt2notion` always produce the current source/A/B note bundle, clean ASR-like transcripts including auto captions, and delete legacy single-summary/entity prompt paths.

**Architecture:** Replace mode branching in `pipeline.prepare_content()` with a bundle-only flow. Introduce a small cleanup-policy helper so manual subtitles can skip cleanup while auto captions, webpage transcripts, and ASR are cleaned. Remove legacy summary/entity prompt bindings, backend methods, tests, and docs.

**Tech Stack:** Python 3.11+, Typer, pytest, ruff, existing `NoteBundle`, `Workspace`, and storage protocols.

---

## File Structure

- Modify `src/yt2notion/pipeline.py`: remove output/note mode branches, entity extraction, legacy summary path, and add cleanup policy.
- Modify `src/yt2notion/models/base.py`: remove legacy summary/entity dataclasses and protocol methods not used by bundle-only.
- Modify `src/yt2notion/models/claude_code.py`, `anthropic_api.py`, `codex_cli.py`: remove legacy summary/entity methods; keep compose methods.
- Modify `src/yt2notion/workspace.py`: keep bundle artifact; remove summary/entity helpers if no tests need them.
- Delete old prompt files listed in the spec.
- Modify tests to assert bundle-only behavior and cleanup policy.
- Modify docs/config: `PROJECT_MAP.md`, `README.md`, `config.example.yaml`, `handoff.md`.

## Task 1: Transcript cleanup policy

- [ ] Add tests in `tests/test_pipeline.py`:
  - manual subtitle segments skip `_step_review()` and no `reviewed.json` is written.
  - auto-caption-like segments with `source="auto_caption"` are cleaned and saved to `reviewed.json`.
  - ASR segments continue to be cleaned.
- [ ] Implement `_should_cleanup_transcript(transcripts: list[dict]) -> bool` in `src/yt2notion/pipeline.py`.
- [ ] Update the review branch in `prepare_content()` to call `_step_review()` only when `_should_cleanup_transcript()` is true.
- [ ] Run: `PYTHONPATH=src pytest tests/test_pipeline.py -q`.

## Task 2: Bundle-only pipeline routing

- [ ] Add tests in `tests/test_pipeline.py` and `tests/test_config.py` that `prepare_content()` always returns `note_bundle`, rejects `mode="full"`, and does not write `summary.json` / `entities.json`.
- [ ] Remove `_resolve_note_mode()` and legacy single-summary routing from `prepare_content()`.
- [ ] Keep `run_pipeline()` publishing only `prepared.note_bundle`; reject non-Obsidian publish backend before publishing.
- [ ] Update CLI prepare payload tests to expect bundle output only.
- [ ] Run: `PYTHONPATH=src pytest tests/test_pipeline.py tests/test_config.py -q`.

## Task 3: Delete legacy prompts and backend methods

- [ ] Delete prompt files: `chinese.md`, `extract_chapters.md`, `extract_entities.md`, `reduce_entities.md`, `review_with_context.md`, `summarize*.md`, `synthesize.md`.
- [ ] Remove legacy methods from `Summarizer` and backend classes: `summarize`, `review_and_summarize`, `to_chinese`, `summarize_chunk`, `synthesize`.
- [ ] Remove entity extraction calls and tests that only cover removed behavior.
- [ ] Keep `review.md`, `topic_segment.md`, `compose_guide.md`, `compose_longform.md`, `compose_note_metadata.md`.
- [ ] Run: `PYTHONPATH=src pytest tests/test_prompts.py tests/test_note_bundle.py tests/test_pipeline.py -q`.

## Task 4: Docs and final validation

- [ ] Update `PROJECT_MAP.md` as the canonical pipeline/prompt/artifact map.
- [ ] Update `README.md` and `config.example.yaml` to describe bundle-only output.
- [ ] Update `handoff.md` with branch, scope, validation, and PR status.
- [ ] Run full local validation:
  - `PYTHONPATH=src pytest tests/ -q`
  - `ruff check src/yt2notion tests`
- [ ] Open PR(s), self-review the diff, fix findings, rerun tests, then merge after all checks pass.
