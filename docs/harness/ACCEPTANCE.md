# ACCEPTANCE

Status: accepted

## Done Definition

- A watch URL containing `list` and `index` is processed as one video.
- Manual English captions are selected when preferred Chinese captions do not
  exist, using one subtitle download call.
- `transcribe --no-video` with captions calls neither video/audio download nor
  ASR.
- `transcribe --no-video` without captions downloads audio directly.
- All three application entry points use the same `MediaAcquireResult` and
  acquisition implementation.
- Split content/transcript result types and acquisition methods are deleted.
- LLM timeout and retry count are configurable; a timeout does not multiply
  into three 120-second waits by default.
- Existing checkpoint/quota behavior and source/A/B publishing remain covered.
- Full local pytest and Ruff checks pass without remote calls.
- A live run against playlist lesson 3 records stage durations and produces
  transcript artifacts without ASR when captions are present.
