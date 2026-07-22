# DECISIONS

Status: accepted

## Decision Log

### 2026-07-22: Explicit use-case Interface over generic workflow engine

Status: accepted

Decision: expose `prepare`, `process`, and `transcribe` through `Yt2Notion`; keep ordering explicit and fixed.

Alternatives considered: generic DAG, orchestrator/nodes, single intent-driven `run()`.

Consequences: less speculative extensibility; clearer safety and caller intent; introduce recipes only after a second real processing order exists.

### 2026-07-22: Capability Interfaces with config-selected primary Adapters

Status: accepted

Decision: use Protocols at real provider variation points. Composition root selects a primary Adapter explicitly from config. No automatic URL routing or registry.

Consequences: provider behavior is replaceable/testable without coupling use cases to provider names.

### 2026-07-22: High-level MediaSource Interface

Status: accepted

Decision: MediaSource owns one acquisition operation with typed profiles/results rather than separate metadata/subtitle/audio/video Protocols.

Consequences: provider coordination and options retain Locality; request/result invariants must avoid optional-field bags.

### 2026-07-22: Transcription lifecycle stays in a deep Module

Status: accepted

Decision: chunking, checkpoint, quota policy, fallback, and provider outcome belong to `TranscriptionEngine`; provider Adapters only transcribe a valid audio input.

Consequences: two use cases share one test surface; provider-specific errors must normalize into common transcription errors.
