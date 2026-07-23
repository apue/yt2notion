# IMPLEMENTATION_PLAN

Status: accepted

## Execution Order

1. Add characterization and Interface contract tests for current CLI, artifacts,
   resume/fresh execution, quota fallback, and backend attribution.
2. Introduce a high-level `MediaSource` Protocol, typed acquisition data, yt-dlp
   Adapter, and explicit config factory while reusing `extract.py` behavior.
3. Extract the ASR chunk/checkpoint/quota lifecycle from `pipeline.py` into one
   `TranscriptionEngine`, retaining the existing `Transcriber` provider Seam.
4. Add the typed `Yt2Notion` application Interface and composition root for
   `prepare`, `process`, and `transcribe`.
5. Route CLI and agent callers through the application Interface. Convert
   `pipeline.py` and `media_transcribe.py` to thin compatibility facades/helpers.
6. Fix standalone config discovery and actual backend outcome reporting without
   changing artifact filenames or JSON contracts.
7. Update `PROJECT_MAP.md` first for changed structure/extension facts, then
   synchronize entry documentation and handoff state.
8. Run focused tests, full pytest, ruff check, format check, architecture review,
   review fixes, and the same local validation again. No remote calls.

## Implementation Constraints

- Do not introduce generic Node/DAG/registry infrastructure.
- Keep provider-specific commands/options inside Adapters.
- Keep chunking/checkpoint/fallback policy inside `TranscriptionEngine`.
- Preserve lazy fallback construction and checkpoint compatibility.
- Preserve existing public imports and CLI behavior through behavior-free facades.
- Do not stage or modify unrelated `.codex/config.toml` and `.gitignore` changes.
- Do not modify prompts, credentials, or publish to external storage.

## Completion Evidence

- Acceptance checklist is satisfied by tests or direct code inspection.
- Full local tests and static checks pass.
- Review findings are resolved and locally revalidated.
- PR contains only intended implementation, tests, and documentation.
