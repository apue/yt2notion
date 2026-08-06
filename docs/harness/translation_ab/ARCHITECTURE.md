# Architecture

`Yt2Notion.translation_experiment()` reuses the existing subtitle-first
`transcribe()` use case, then delegates to `TranslationExperimentRunner`.

The experiment package has four seams:

- `source.py`: typed source contract and deterministic semantic grouping;
- `generator.py`: two prompt strategies and strict ID-based response parsing;
- `artifacts.py`: deterministic metrics, balanced blinding, and file rendering;
- `service.py`: orchestration and timing.

The existing `LLMCaller` Protocol and `model.translate_model` factory binding are
reused. The command has no storage dependency and therefore cannot publish.
Each successful strategy is persisted immediately with its source SHA-256 and
exact ordered IDs. A later run reuses it only when all three match.
