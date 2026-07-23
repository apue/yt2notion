# IMPLEMENTATION_PLAN

Status: in_progress

1. Remove compatibility and Agent files plus their isolated tests.
2. Narrow config, storage, models, CLI, and documentation to supported paths.
3. Introduce one `NoteComposer` over the existing `LLMCaller` interface and
   reduce provider adapters to invocation behavior.
4. Move retained ASR/application assertions out of `test_pipeline.py`.
5. Run focused then full regression/contract checks.
6. Create PR, run two-axis review, fix findings, retest, and merge.

Stop if ASR artifact/state behavior changes or a deleted surface has a current
production caller.
