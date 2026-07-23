# REUSE_CLEANUP_REPORT

Status: accepted

## Reuse

- `application.Yt2Notion`: sole use-case interface.
- `transcribe.TranscriptionEngine`: ASR lifecycle and test surface.
- `MediaSource`, `Transcriber`, and `LLMCaller`: real provider seams.
- `Workspace`: artifact/checkpoint contract.
- `NoteBundle`: sole publish model.

## Delete

- pass-through pipeline helpers and tests coupled to their patch points;
- file-backed Agent product;
- legacy single-note storage implementation and model;
- duplicated provider-specific note composition;
- historical implementation plans already represented by current architecture.

## Search Evidence

`rg` and `sg` found no production caller of `yt2notion.pipeline`; legacy
storage calls exist only in storage implementations/tests; Agent imports are
limited to the Agent CLI/runtime/tests.

## Risks

This intentionally removes old public entry points. ASR behavior and artifact
contracts are not changed and retain their regression coverage.
