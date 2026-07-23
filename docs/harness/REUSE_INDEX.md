# REUSE_INDEX

Status: accepted

- `application.Yt2Notion`: reuse as the sole orchestration interface.
- `media_source.MediaSource`: retain provider seam.
- `transcribe.Transcriber`: retain provider seam.
- `transcribe.TranscriptionEngine`: retain deep ASR module.
- `models.llm.LLMCaller`: extend to all LLM providers.
- `workspace.Workspace`: retain artifact/checkpoint contract.
- `models.NoteBundle`: retain sole publish model.

Avoid introducing compatibility wrappers or a second queue/orchestration
product.
