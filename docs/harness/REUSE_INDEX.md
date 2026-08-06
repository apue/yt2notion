# REUSE_INDEX

Status: accepted

- `application.Yt2Notion`: reuse as the sole orchestration interface.
- `media_source.MediaSource`: retain provider seam.
- `transcribe.Transcriber`: retain provider seam.
- `transcribe.TranscriptionEngine`: retain deep ASR module.
- `models.llm.LLMCaller`: extend to all LLM providers.
- `workspace.Workspace`: retain artifact/checkpoint contract.
- `models.NoteBundle`: retain sole publish model.
- `extract.extract_metadata`: extend its result to carry available subtitle
  language information from the existing yt-dlp probe.
- `TranscriptionEngine.transcribe_workspace`: reuse as the only subtitle/audio
  dispatch point for all application entry points.
- `Workspace`: reuse video-id workspaces and transcript artifact persistence.

Avoid introducing compatibility wrappers or a second queue/orchestration
product.
