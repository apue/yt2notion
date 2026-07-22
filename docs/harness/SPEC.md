# SPEC

Status: accepted

## Goal

Refactor yt2notion around cohesive use-case Modules and provider Interfaces so callers depend on stable behavior rather than pipeline private functions or concrete providers.

## Non-Goals

- No generic node, DAG, scheduler, registry, or dynamic plugin discovery framework.
- No new remote provider such as ElevenLabs in this change.
- No changes to prompt structure, note-bundle semantics, or automatic publishing policy.
- No performance optimization of ASR behavior without benchmark evidence.
- No agent-runtime or storage rewrite beyond adapting callers to the new application Interface.

## Users and Use Cases

- CLI/agent caller: prepare a source/A/B bundle without publishing.
- Explicit process caller: prepare and publish through the configured supported publisher.
- Transcript-only caller: download video, extract audio, transcribe, and write local artifacts only.
- Maintainer: add another media-source or transcription Adapter without changing use-case control flow.

## Requirements

### Functional

- Provide a `Yt2Notion` application Interface with explicit `prepare`, `process`, and `transcribe` behavior.
- Provide a high-level `MediaSource` Protocol selected explicitly from config by a composition root; initial production Adapter is yt-dlp.
- Keep the existing `Transcriber` provider Seam and type factories to return that Protocol.
- Move audio planning, chunking, checkpoint reconciliation, Groq hourly wait, daily fallback, and result assembly into a deep `TranscriptionEngine` Module.
- Main preparation and standalone transcription must reuse `TranscriptionEngine`; standalone code must not import private pipeline functions.
- Preserve current CLI commands and compatibility imports.
- Preserve Workspace artifact filenames and JSON shapes unless `PROJECT_MAP.md` is updated first.
- Standalone config resolution must support the user's existing `~/.yt2notion/config.yaml`, the agent config, explicit config, and repo config.
- A fresh run may invalidate stale artifacts; a compatible resume at transcription must preserve completed checkpoint chunks.
- Transcript Markdown must report the actual backend outcome, including mixed/fallback execution.

### Non-functional

- High cohesion: provider behavior stays inside its Adapter; ASR lifecycle stays inside `TranscriptionEngine`.
- Low coupling: use cases depend on Protocols and result types, not concrete provider modules.
- Test through public Module Interfaces with fake Adapters and temporary Workspace directories.
- No online ASR, LLM, Notion, or Obsidian calls during validation/review.

## Open Questions

None blocking. Detailed request/result field design is delegated to the implementation as long as acceptance criteria and decisions remain true.

## Acceptance Link

See `ACCEPTANCE.md`.
