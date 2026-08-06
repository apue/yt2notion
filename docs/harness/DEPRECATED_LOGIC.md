# DEPRECATED_LOGIC

Status: accepted

All previously recorded removal conditions are satisfied by the application
and transcription-engine contract tests.

Delete in the subtitle-first repair:

- `MediaAcquireRequest.profile`;
- `ContentMediaAcquireResult` and `TranscriptMediaAcquireResult`;
- `YtDlpMediaSource._acquire_content` and `_acquire_transcript` split;
- the transcribe-only forced video-download path.

Delete in this change:

- `pipeline.py` compatibility facade and public helper wrappers;
- `extract_cmd.py`;
- `agent_runtime.py`, `agent_worker.py`, and `yt2notion agent`;
- Notion and legacy single-note storage contracts;
- `openai_api`, `note_mode`, and unsupported `markdown` aliases;
- history-only `docs/superpowers` plans/specs.

<!-- generated-deprecated-logic:start -->
## Generated Deprecated Candidates

- `docs/harness/DEPRECATED_LOGIC.md`
<!-- generated-deprecated-logic:end -->
