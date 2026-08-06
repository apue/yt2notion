# Reuse and Cleanup Report

## Reused

- `Yt2Notion.transcribe()` for subtitle-first acquisition and canonical transcript artifacts.
- `LLMCaller` and `create_llm_caller(..., model_key="translate_model")` for provider-neutral generation.
- Existing prompt loader and JSON-array parser.
- `VideoMeta`, `Workspace`, and timestamp formatting contracts.

## Added seams

- Source construction is independent of providers and artifact rendering.
- Generation depends only on the existing `LLMCaller` Protocol.
- Checkpoint validation and blind rendering are independent of orchestration.

## Removed or avoided

- No legacy translation format or compatibility adapter.
- No second acquisition, ASR, storage, or summary path.
- No character-count quality gate.
- No subjective scoring of every intermediate step.
- No unsupported formula or symbol invention; explicit notation normalization
  remains part of faithful translation.
- No one-function implementation combining source parsing, model calls, validation, and rendering.
