# ARCHITECTURE

Status: accepted

## Summary

Use explicit application use cases backed by deep domain Modules and capability-specific provider Interfaces. Keep pipeline ordering explicit. Do not introduce generic orchestrator/nodes.

```text
CLI / agent worker / compatibility facades
                  |
                  v
           Yt2Notion Interface
       prepare | process | transcribe
          /          |          \
 Acquisition  TranscriptionEngine  ContentPreparation / Publishing
      |               |                       |
 MediaSource      Transcriber              existing model/storage
  Interface        Interface                  Interfaces
      |          /      |      \
 yt-dlp Adapter  Groq  Remote  Fake
```

## Modules and Seams

### `Yt2Notion`

- External Interface for the three supported use cases.
- Owns explicit ordering, stop points, no-publish guarantees, progress/failure translation, and result assembly.
- Does not contain provider-specific commands or ASR chunk lifecycle.

### `MediaSource`

- High-level Protocol: one acquisition operation with a typed request/profile and discriminated result.
- Initial production Adapter uses existing yt-dlp/webpage extraction implementation.
- Provider configuration is injected at construction; provider-specific options do not leak into application use cases.
- Composition root selects one primary Adapter explicitly from config. No URL-string provider routing or registry.

### `TranscriptionEngine`

- Deep Module containing subtitle/audio transcription policy, plan/state/chunks, upload budgets, hourly waiting, daily fallback, checkpoint reconciliation, and final result/backend outcome.
- Depends on `Transcriber` provider Adapters and Workspace persistence.
- State machine remains internal because it represents genuine ASR lifecycle states.

### Existing Modules

- `ContentPreparation` can continue to use segment/topic/review/note-bundle functions during this bounded refactor.
- Existing Summarizer, LLMCaller, Storage, and Transcriber Protocols remain provider Seams.
- `pipeline.py` and `media_transcribe.py` become compatibility facades or rendering helpers and must not own duplicated orchestration/state.

## Data and Control Flow

1. Composition root loads validated config and creates provider Adapters.
2. Caller invokes one `Yt2Notion` use case.
3. Application acquires or restores source/Workspace state.
4. Application calls `TranscriptionEngine` only when transcript artifacts are required.
5. Prepare continues through conditional topic split/review and note-bundle composition.
6. Process alone publishes after explicit invocation and supported backend validation.
7. Transcribe stops after transcript JSON/Markdown artifacts.

## Dependency Categories

- In-process: segmentation, review policy, note-bundle composition.
- Local-substitutable: Workspace filesystem, yt-dlp/ffmpeg subprocesses.
- Remote owned: current remote ASR Adapter.
- True external: Groq, model providers, Notion.

## Compatibility Strategy

- Preserve imports from `yt2notion.pipeline` and `yt2notion.media_transcribe` through thin facades while CLI/tests migrate.
- Read existing Workspace artifacts without migration.
- Remove compatibility facades only in a later explicitly approved change.

## Alternatives Considered

- Generic Orchestrator + Nodes: rejected because ordering is canonical, graph variability is absent, and Node contracts would expose artifact/state mechanics.
- Whole-pipeline state machine: rejected; only transcription has a genuine complex lifecycle.
- Only extract `_transcribe_from_audio`: rejected because callers would still duplicate acquisition, cleanup, factories, and result attribution.
- Intent-only `run()` Interface: rejected in favor of explicit use-case methods that prevent illegal publish combinations.

## Risks

- Large code movement can silently change checkpoint semantics. Mitigate with characterization/contract tests before deleting old paths.
- Compatibility facades can become permanent shallow Modules. Record removal conditions and keep them behavior-free.
- MediaSource may become an oversized Interface. Keep one high-level acquisition operation and provider-specific configuration internal.
