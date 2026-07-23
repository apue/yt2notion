# SPEC

Status: accepted

## Goal

Reduce `yt2notion` to its supported use cases and real provider seams:

- keep `process`, `prepare`, and `transcribe`;
- keep Obsidian source/A/B bundle publishing;
- keep media-source, transcription, and LLM provider adapters;
- remove compatibility-only, legacy single-note, and local queue surfaces.

## Non-Goals

- No ASR behavior or performance changes.
- No prompt-template changes.
- No new provider, workflow engine, registry, or plugin discovery.
- No live ASR, LLM, or storage calls during validation.

## Requirements

- Delete the `pipeline` compatibility facade and test orchestration through
  `Yt2Notion` and `TranscriptionEngine`.
- Delete the legacy `extract_cmd` entry point.
- Delete the file-backed `agent` runtime and its CLI commands.
- Make Obsidian bundle publishing the only storage contract.
- Remove legacy Notion/single-note models and unsupported backend aliases.
- Move note prompt assembly and response parsing into one composer; provider
  adapters only implement text-in/text-out LLM calls.
- Preserve workspace artifacts, ASR checkpoint/quota behavior, and the three
  supported CLI commands.
