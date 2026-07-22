# DEPRECATED_LOGIC

Status: accepted

## Deprecated or Legacy Logic

- `src/yt2notion/media_transcribe.py` orchestration
  - Replacement: `Yt2Notion.transcribe` plus rendering/result compatibility helpers.
  - Removal condition: CLI and tests use application Interface; compatibility import policy is separately approved.
- `src/yt2notion/pipeline.py` ASR chunk/checkpoint private cluster
  - Replacement: `transcribe/engine.py`.
  - Removal condition: engine contract/regression coverage passes and both callers use it.
- `src/yt2notion/extract_cmd.py`
  - Replacement: normal CLI application Interface.
  - Removal condition: no documented/external caller remains; not removed in this task.

## Deletion Candidates

- Tests that patch `_step_transcribe` or `_transcribe_from_audio`
  - Evidence: implementation-detail coupling identified in architecture review.
  - Required validation: equivalent application/engine contract tests.
