# yt2notion

Extract YouTube subtitles, summarize with LLM, publish to Notion — in one command.

## Features

- **Smart subtitle extraction**: prioritizes Chinese subs > English subs > auto-generated captions
- **Two-stage LLM processing**: Sonnet for structural summarization, Opus for natural Chinese output
- **Timestamped key points**: clickable YouTube timestamp links in your notes
- **Always credits the source**: channel name, video title, and URL included automatically
- **Pluggable backends**: swap LLM providers (Claude Code / Anthropic API / OpenAI) and storage (Notion / Obsidian)
- **Zero API cost option**: use your existing Claude Code subscription via `claude -p`

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
```

## Prerequisites

- Python 3.11+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installed and on PATH
- One of:
  - [Claude Code](https://code.claude.com) (Pro/Max subscription) — zero additional cost
  - Anthropic API key — pay per token
- Notion integration token (if using Notion storage)

## Model Backends

| Backend | Config value | Cost | Requirements |
|---------|-------------|------|--------------|
| Claude Code CLI | `claude_code` | Included in subscription | `claude` on PATH |
| Anthropic API | `anthropic_api` | ~$0.30/video | `ANTHROPIC_API_KEY` |
| OpenAI API | `openai_api` | varies | PRs welcome! |

## Storage Backends

| Backend | Config value | Status |
|---------|-------------|--------|
| Notion | `notion` | ✅ Implemented |
| Obsidian | `obsidian` | 🚧 PRs welcome |
| Markdown files | `markdown` | 🚧 PRs welcome |

## Configuration

See [config.example.yaml](config.example.yaml) for all options.

## How It Works

```
YouTube URL
    │
    ├─ yt-dlp: extract subtitles + metadata
    ├─ process: clean SRT → timestamped chunks
    ├─ Sonnet: structured summary with timestamps
    ├─ Opus: natural Chinese rewrite
    └─ Notion API: create page with tags & links
```

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
