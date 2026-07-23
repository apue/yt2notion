# ACCEPTANCE

Status: accepted

## Done Definition

- [x] `Yt2Notion.prepare/process/transcribe` exist with comprehensive type hints.
- [x] `MediaSource` is a high-level Protocol and yt-dlp is selected by an explicit factory/composition root.
- [x] Main and transcript-only use cases share `TranscriptionEngine`.
- [x] `media_transcribe.py` does not import `_step_segment` or `_transcribe_from_audio` from `pipeline.py`.
- [x] `pipeline.py` no longer owns the ASR chunk/checkpoint/fallback state machine.
- [x] Existing public CLI behavior and artifact contracts remain compatible.
- [x] Existing `~/.yt2notion/config.yaml` is considered by standalone config resolution.
- [x] Compatible transcription resume preserves completed chunks; explicit fresh execution clears them.
- [x] Markdown backend attribution reflects primary-only, fallback-only, or mixed execution accurately.
- [x] New contract/regression tests and full local pytest/ruff pass.
- [x] `PROJECT_MAP.md`, compatibility notes, and `handoff.md` match implementation.

## Acceptance Criteria

1. Given fake MediaSource and Transcriber Adapters, when each application use case runs, then expected artifacts/results are produced without invoking unrelated publisher/model Adapters.
2. Given a persisted transcribe plan/state with completed chunk payloads, when transcription resumes compatibly, then completed chunks are not recomputed.
3. Given daily-quota fallback, when the result is rendered, then actual provider usage is preserved and displayed.
4. Given existing CLI commands and compatibility functions, when invoked in unit tests, then caller-visible result and error behavior remains compatible.
5. Given config backend selection, when an unknown media-source or ASR backend is requested, then a scoped configuration/factory error is raised.

## Manual Review Checklist

- [x] No generic Node/DAG abstraction was introduced.
- [x] Application and provider Interfaces remain small and behavior-oriented.
- [x] Main pipeline retains metadata-driven decisions.
- [x] No prompt files or secret values were modified.
- [x] No remote verification was executed.

## Out of Scope

- ElevenLabs implementation.
- Third-party plugin discovery.
- Agent runtime state-store redesign.
- Storage Protocol cleanup beyond required compatibility.
