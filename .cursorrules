# yt2notion Project Rules

## 1. Role and Context
You are an expert Python developer working on the `yt2notion` project, a CLI pipeline tool that extracts YouTube/Podcast subtitles, summarizes them using LLMs, and publishes them to Notion.

## 2. Core Constraints (CRITICAL)
- **NEVER** automatically publish to Notion without an explicit user confirmation step.
- **NEVER** modify the format or structural layout of markdown files in the `prompts/` directory; they are prompt templates, not standard markdown documentation.
- ALWAYS include source credit in any generated output (channel name, video title, URL).
- Any performance-sensitive changes (especially in the ASR pipeline) MUST be backed by benchmark data.

## 3. Technology Stack & Tooling
- **Language**: Python 3.11+
- **Dependency Management**: `uv` (use `uv sync` to install/update dependencies, `uv run ...` to execute).
- **CLI Framework**: `typer`
- **Linting & Formatting**: `ruff` (run `uv run ruff check src/` and `uv run ruff format src/`)
- **Testing**: `pytest` (fixtures belong in `tests/conftest.py`)

## 4. Code Style & Architecture
- **Type Hints**: All public functions and methods MUST have comprehensive type hints.
- **Interface Segregation**: Use `typing.Protocol` for defining interfaces (e.g., `Summarizer`, `LLMCaller`, `Storage`), do NOT use standard `abc.ABC`.
- **Plugin Architecture**: Implementations are selected dynamically at runtime via `config.yaml` (`backend` field). Maintain this loose coupling.
- **Error Handling**: Define and use custom exception classes scoped within their respective modules.

## 5. Pipeline Overview
The core pipeline consists of 5 metadata-driven steps. All decisions should be based on metadata signals, not URL pattern matching:
1. **DOWNLOAD**: Extract metadata and subtitles/audio via `yt-dlp`.
2. **SEGMENT**: Generate chapter markers (from existing chapters -> LLM extraction -> Topic segmentation).
3. **TRANSCRIBE**: Extract or generate text (existing subs -> MLX-Whisper/Qwen ASR).
4. **REVIEW**: LLM-assisted correction of ASR errors.
5. **SUMMARIZE**: Multi-step LLM summarization (Map-Reduce: e.g., Sonnet for structure, Opus for Chinese synthesis) and Notion API delivery.
