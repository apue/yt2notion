# ARCHITECTURE

Status: accepted

```text
CLI: process | prepare | transcribe
                  |
             Yt2Notion
                  |
       MediaSource.acquire(request)
                  |
       metadata -> preferred subtitle
                  | no subtitle
        keep_video? video->audio : direct audio
                  |
      TranscriptionEngine.transcribe_workspace
                  |
       transcript artifacts -> optional composition/publish
```

`MediaAcquireRequest.keep_video` is the only acquisition-mode choice. The
former content/transcript profile split is deleted. `MediaAcquireResult` owns
optional subtitle, audio, and video paths; application use cases decide where
to stop after the shared acquisition/transcription stages.

Subtitle selection uses the language maps returned by the existing metadata
probe. It does not launch one `yt-dlp` process per preferred language.

External ASR and LLM calls remain provider adapters. Retry policy is bounded at
the adapter boundary and phase durations are observable at the application
boundary.
