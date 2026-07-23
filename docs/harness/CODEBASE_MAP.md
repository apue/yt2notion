# CODEBASE_MAP

Status: accepted

- `application.py`: `process`, `prepare`, and `transcribe` use cases.
- `media_source/`: acquisition interface and yt-dlp adapter.
- `transcribe/`: ASR provider adapters and stateful engine.
- `models/llm.py`: provider text-call interface and adapters.
- `models/note_composer.py`: note prompt assembly and parsing.
- `storage/`: bundle storage interface and Obsidian adapter.
- `workspace.py`: local artifact and checkpoint persistence.
- `tests/`: public-interface, provider-contract, and state regression tests.
- `PROJECT_MAP.md`: canonical pipeline and artifact facts.
