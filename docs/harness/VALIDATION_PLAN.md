# VALIDATION_PLAN

Status: accepted

## Validation Mode

Selected modes: regression-test + contract-test + review-only architecture check.

Reason: this is a behavior-preserving refactor that changes public/internal Interfaces, checkpoint ownership, and provider composition.

## Commands

```bash
env -u ANTHROPIC_API_KEY uv run --extra dev pytest tests/ -q
uv run --extra dev ruff check src/yt2notion tests
uv run --extra dev ruff format --check <changed-python-files>
```

Run focused tests first for application, media source, transcription engine, pipeline compatibility, CLI, Workspace, Groq, and factories.

## Pass Criteria

- Full local suite passes with zero failures.
- Full-repository Ruff check and changed-file format check pass.
- No test invokes remote ASR, Groq, model, Notion, or Obsidian services.
- Contract tests cover all provider/application Interfaces and fake Adapters.
- Regression tests cover resume preservation, fresh invalidation, quota fallback, actual backend attribution, and no-publish safety.
- `rg` confirms standalone code no longer imports pipeline private functions and pipeline no longer owns the ASR state machine.

## Manual Checks

- [x] Compare implementation with SPEC/ARCHITECTURE/DECISIONS.
- [x] Confirm no generic Node/DAG framework or registry was introduced.
- [x] Confirm compatibility facades contain no domain behavior.
- [x] Review artifact changes against PROJECT_MAP.md.

## Known Gaps

- No live provider verification during review.
- ASR performance is expected to remain unchanged; if implementation changes encoding/chunk parameters, stop and obtain benchmark evidence.
