# ARCHITECTURE

Status: accepted

```text
CLI: process | prepare | transcribe
                  |
             Yt2Notion
        /         |          \
 MediaSource  TranscriptionEngine  ContentPreparation
   adapter        |                 |          |
              Transcriber       NoteComposer  Storage
                adapters         LLMCaller    Obsidian
                                 adapters
```

`Yt2Notion` is the sole application interface. `TranscriptionEngine` owns the
stateful ASR lifecycle. `NoteComposer` owns provider-independent prompt
assembly and parsing. Provider adapters stop at true external seams.

Compatibility pass-through modules and the separate file-queue product are
removed instead of layered with more tests.
