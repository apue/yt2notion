# yt2notion

Extract media content (YouTube videos, Podcasts), summarize with LLM, publish to Notion / Obsidian — in one command.

## Features

- **Smart subtitle extraction**: prioritizes Chinese subs > English subs > auto-generated captions
- **Podcast ASR support**: local Qwen3-ASR on Apple Silicon, no cloud API needed
- **Multi-stage LLM pipeline**: Haiku (review/segment) → Sonnet (map) → Opus (reduce)
- **Topic-aware segmentation**: LLM finds natural topic boundaries for long content
- **Timestamped key points**: clickable timestamp links in your notes
- **Fun facts extraction**: hot takes, nerd stats, and media mentions pulled from content
- **Entity extraction**: identifies people, places, tools, and their relationships — builds a knowledge graph via `[[wiki-links]]`
- **Always credits the source**: channel name, video title, and URL included automatically
- **Pluggable backends**: swap LLM providers and storage (Notion / Obsidian)
- **Workspace persistence**: resume interrupted pipelines from any step
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
| Obsidian | `obsidian` | ✅ Implemented |
| Markdown files | `markdown` | 🚧 PRs welcome |

## Configuration

See [config.example.yaml](config.example.yaml) for all options.

## How It Works

```
YouTube / Podcast URL
    │
    1. DOWNLOAD ─── yt-dlp: metadata + subtitles or audio
    │
    2. SEGMENT ──── chapters → LLM extract from description → N/A
    │
    3. TRANSCRIBE ─ subtitle assignment or per-segment ASR
    │       │
    │       └── 3.5 TOPIC SEGMENT ── Haiku splits oversized segments
    │
    4. REVIEW ───── Haiku cleans ASR errors, fixes proper nouns
    │
    5. EXTRACT ──── Haiku identifies entities and relationships
    │
    6. SUMMARIZE ── Sonnet map (per-segment) + Opus reduce (global)
    │       │
    │       └── 6.5 DEFERRED REVIEW ── for long content: review + transcript after summary
    │
    └── Storage: summary + transcript (Notion page / Obsidian note)
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
