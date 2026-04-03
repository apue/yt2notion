# yt2notion

Extract media content (YouTube videos, Podcasts), summarize with LLM, publish to Notion / Obsidian — in one command.

## Features

- **Smart subtitle extraction**: prioritizes Chinese subs > English subs > auto-generated captions
- **Podcast ASR support**: local Qwen3-ASR on Apple Silicon, no cloud API needed
- **Multi-stage LLM pipeline**: Haiku (review/segment) → Sonnet (map) → Opus (reduce)
- **Topic-aware segmentation**: LLM finds natural topic boundaries for long content
- **Dual output modes**: `summary` by default, optional `full` for reviewed transcript + summary
- **Timestamped key points**: clickable timestamp links in your notes
- **Fun facts extraction**: hot takes, nerd stats, and media mentions pulled from content
- **Entity extraction**: identifies people, places, tools, and their relationships — builds a knowledge graph via `[[wiki-links]]`
- **Always credits the source**: channel name, video title, and URL included automatically
- **Pluggable backends**: swap LLM providers and storage (Notion / Obsidian)
- **Workspace persistence**: resume interrupted pipelines from any step
- **Zero API cost option**: use your existing Claude Code subscription via `claude -p`
- **Codex backend support**: use local `codex exec` with GPT-5.x style models

## Quick Start

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/YOUR_USERNAME/yt2notion.git
cd yt2notion
uv sync --extra notion

# Configure
cp config.example.yaml config.yaml
# Edit config.yaml with your Notion token and preferences

# Run
uv run yt2notion "https://www.youtube.com/watch?v=VIDEO_ID"

# Prepare JSON for Claude/Codex wrappers without publishing
uv run yt2notion prepare "https://www.youtube.com/watch?v=VIDEO_ID" --mode summary
```

## Prerequisites

- Python 3.11+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installed and on PATH
- One of:
  - [Claude Code](https://code.claude.com) (Pro/Max subscription) — zero additional cost
  - [Codex CLI](https://platform.openai.com/docs/codex) — local `codex` command available
  - Anthropic API key — pay per token
- Notion integration token (if using Notion storage)

## Model Backends

| Backend | Config value | Cost | Requirements |
|---------|-------------|------|--------------|
| Claude Code CLI | `claude_code` | Included in subscription | `claude` on PATH |
| Codex CLI | `codex_cli` | Depends on your Codex setup | `codex` on PATH |
| Anthropic API | `anthropic_api` | ~$0.30/video | `ANTHROPIC_API_KEY` |
| OpenAI alias | `openai_api` | Depends on your Codex setup | routes to `codex_cli` |

## Storage Backends

| Backend | Config value | Status |
|---------|-------------|--------|
| Notion | `notion` | ✅ Implemented |
| Obsidian | `obsidian` | ✅ Implemented |
| Markdown files | `markdown` | 🚧 PRs welcome |

## Configuration

See [config.example.yaml](config.example.yaml) for all options.

Key options:
- `output.mode: summary|full`
- `model.backend: claude_code|codex_cli|anthropic_api|openai_api`
- `extract.asr.restart_before_transcribe` / `extract.asr.restart_on_unhealthy` for ASR self-healing

ASR auto-restart operations and runbook:
- [docs/operations/asr-service.md](docs/operations/asr-service.md)

## How It Works

Pipeline truth, step order, and artifact contracts live in [PROJECT_MAP.md](PROJECT_MAP.md). This README keeps the user-facing summary only: download metadata and media, segment by chapters or topic boundaries, transcribe from subtitles or ASR, optionally keep a reviewed transcript in `full` mode, summarize, then publish to storage.

If you need the canonical pipeline map, follow [PROJECT_MAP.md](PROJECT_MAP.md) first.

## Development

```bash
uv sync --extra notion --extra anthropic
uv run pytest tests/ -v
uv run ruff check src/
```

## Contributing

PRs welcome! Especially for:
- New storage backends (Obsidian, plain Markdown, etc.)
- New model backends (OpenAI, Gemini, local models)
- Better prompt templates
- i18n support for output languages other than Chinese

## License

MIT
