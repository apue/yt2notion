# SPEC

Status: accepted

## Goal

Make all supported CLI entry points use one subtitle-first media acquisition
pipeline so a public video with usable captions never downloads media or starts
ASR unnecessarily.

## Non-Goals

- No new CLI command or compatibility wrapper.
- No prompt-template or Obsidian publishing changes.
- No remote ASR, LLM, or storage calls in automated tests.
- No compatibility preservation for the split content/transcript acquisition
  result types.

## Requirements

- Treat a YouTube watch URL as one video even when it carries playlist query
  parameters.
- Probe metadata once and select the highest-priority available manual caption,
  then the configured automatic caption fallback.
- Make `process`, `prepare`, and `transcribe` reuse the same acquisition path.
- When captions are available, do not download video/audio or initialize ASR.
- When captions are unavailable and `--no-video` is selected, download audio
  directly instead of downloading the best video first.
- Delete the redundant transcript-only acquisition branch and result type.
- Keep ASR restart conditional on actual ASR use and make LLM timeout/retry
  behavior bounded and configurable.
- Emit enough elapsed-time information to compare the repaired path with a
  real next-lesson run.
