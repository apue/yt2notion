# DECISIONS

Status: accepted

## 2026-07-23: Remove compatibility instead of preserving patch points

`Yt2Notion` and `TranscriptionEngine` are the test surfaces. The alpha package
does not retain `pipeline` private-function compatibility.

## 2026-07-23: Keep only the current storage contract

Obsidian source/A/B bundle publishing is supported. Legacy Notion single-note
publishing and the unimplemented Markdown backend are removed.

## 2026-07-23: Remove the file-backed Agent product

Codex can invoke the repository CLI directly. Queue, worker, PID, retry, and
notification semantics are outside this project's supported use cases.

## 2026-07-23: Provider adapters do not own note composition

Provider variation lives at the `LLMCaller` seam. Prompt payload construction
and parsing live once in `NoteComposer`.
