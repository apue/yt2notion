# yt2notion

Extract media content (YouTube videos, Podcasts), compose source/A/B Chinese notes with LLMs, and publish the current bundle to Obsidian — in one command.

## Features

- **Smart subtitle extraction**: prioritizes manual subtitles when available, with ASR fallback for podcasts/audio-only media
- **Podcast ASR support**: Groq primary ASR with optional remote/local fallback
- **Bundle-only LLM pipeline**: always produces `source`, `A 导读`, and `B 扩展` notes
- **Transcript cleanup policy**: manual subtitles skip cleanup; auto captions, webpage transcripts, ASR, and legacy subtitles are cleaned
- **Topic-aware segmentation**: LLM finds natural topic boundaries for ASR-like long transcripts
- **Timestamped source material**: source title, channel, URL, and timestamped transcript context remain available to generated notes
- **Current publish target**: the source/A/B bundle publishes through Obsidian; Notion storage is retained for legacy single-note code paths
- **Always credits the source**: channel name, video title, and URL included automatically
- **Pluggable LLM backends**: swap Codex CLI or Anthropic API model providers
- **Workspace persistence**: resume interrupted pipelines from any step
- **Codex backend support**: use local `codex exec` with GPT-5.x style models

## Quick Start

```bash
# Install uv if you haven't
curl -LsSf https://astral.sh/uv/install.sh | sh

# Clone and install
git clone https://github.com/YOUR_USERNAME/yt2notion.git
cd yt2notion
uv sync --extra notion

# Configure the base pipeline
cp config.example.yaml config.yaml
# Edit config.yaml with your extraction / ASR / model preferences

# One-off run (publishes through the configured storage backend)
uv run yt2notion process "https://www.youtube.com/watch?v=VIDEO_ID"

# Prepare JSON for Claude/Codex wrappers without publishing
uv run yt2notion prepare "https://www.youtube.com/watch?v=VIDEO_ID" --mode summary

# Download media, extract audio, and write transcript artifacts only
uv run yt2notion transcribe "https://www.youtube.com/watch?v=VIDEO_ID"
```

## Queued Agent Workflow

Use the `agent` command group when you want a local file-backed queue that drains URLs one by one into Obsidian.

Fixed behavior for this workflow:
- LLM backend is always `codex_cli`
- Storage backend is always `obsidian`
- Output is always the source/A/B note bundle
- Runtime state lives under `~/.yt2notion-agent/`
- Runtime control plane lives in `~/.yt2notion-agent/agent.yaml`
- Runtime pipeline config lives in `~/.yt2notion-agent/config.yaml`

Agent commands default to `~/.yt2notion-agent/config.yaml` for pipeline settings. Pass `--config` to override that default.

```bash
# Create ~/.yt2notion-agent/agent.yaml, ~/.yt2notion-agent/config.yaml, and runtime AGENTS.md
uv run yt2notion agent init

# Edit runtime control-plane config
$EDITOR ~/.yt2notion-agent/agent.yaml

# Edit runtime pipeline config (used by agent commands unless --config is set)
$EDITOR ~/.yt2notion-agent/config.yaml

# Queue work
uv run yt2notion agent add "https://www.youtube.com/watch?v=VIDEO_ID"
uv run yt2notion agent add "https://example.com/podcast-episode"

# Inspect queue / job state
uv run yt2notion agent status
uv run yt2notion agent list
uv run yt2notion agent show <job-id>
uv run yt2notion agent logs <job-id>

# Retry a failed job
uv run yt2notion agent retry <job-id>

# Debug in the foreground instead of spawning a background worker
uv run yt2notion agent run --foreground
```

The generated `agent.yaml` is intentionally small:

```yaml
vault_path: "/path/to/your/vault"
summaries_dir: "yt2notion/summaries"
transcripts_dir: "yt2notion/transcripts"
workspace_dir: "~/.yt2notion-agent/workspace"
codex_model: "gpt-5.4"
codex_profile: ""
reasoning_effort: "low"
```

Set `codex_profile` when you need `yt2notion` to force a named Codex profile such as `goodhope` instead of using the global default from `~/.codex/config.toml`.

## Prerequisites

- Python 3.11+
- [yt-dlp](https://github.com/yt-dlp/yt-dlp) installed and on PATH
- One of:
  - [Claude Code](https://code.claude.com) (Pro/Max subscription) — zero additional cost
  - [Codex CLI](https://platform.openai.com/docs/codex) — local `codex` command available
  - Anthropic API key — pay per token
- Notion integration token (if using Notion storage)
- An Obsidian vault path (if using Obsidian storage or the queued agent workflow)

## Model Backends

| Backend | Config value | Cost | Requirements |
|---------|-------------|------|--------------|
| Codex CLI | `codex_cli` | Depends on your Codex setup | `codex` on PATH |
| Anthropic API | `anthropic_api` | ~$0.30/video | `ANTHROPIC_API_KEY` |
| OpenAI alias | `openai_api` | Depends on your Codex setup | routes to `codex_cli` |

## Storage Backends

| Backend | Config value | Status |
|---------|-------------|--------|
| Notion | `notion` | Legacy single-note storage only; current bundle publish is not enabled |
| Obsidian | `obsidian` | ✅ Current source/A/B bundle publish target |
| Markdown files | `markdown` | 🚧 PRs welcome |

## Configuration

See [config.example.yaml](config.example.yaml) for all options.

Key options:
- `output.mode: summary` (bundle-only; `full` is no longer supported)
- `model.backend: codex_cli|anthropic_api|openai_api`
- `extract.asr.backend: groq|remote` (recommended: `groq`)
- `extract.asr.fallback_backend: remote|groq|null` (recommended with Groq primary: `remote`)
- `extract.asr.groq.*` for Groq endpoint/model/limits (set key via `GROQ_API_KEY` or config)
- `extract.asr.restart_before_transcribe` / `extract.asr.restart_on_unhealthy` for ASR self-healing

ASR fallback behavior summary:
- Subtitle path still bypasses ASR.
- Audio path uses the primary ASR backend.
- When primary is Groq, hourly quota waits through the current window from persisted chunk checkpoints.
- When primary is Groq, daily quota switches the current failed chunk plus the remaining pending chunks of the same job to `extract.asr.fallback_backend`.
- Checkpoints are reused when resuming from `transcribe`; rerunning from an earlier step rebuilds the transcribe stage from a clean checkpoint set.
- Request errors such as `400/401/403` still fail directly.

ASR auto-restart operations and runbook:
- [docs/operations/asr-service.md](docs/operations/asr-service.md)

## How It Works

Pipeline truth, step order, and artifact contracts live in [PROJECT_MAP.md](PROJECT_MAP.md). This README keeps the user-facing summary only: download metadata and media, segment by chapters or topic boundaries, transcribe from subtitles or ASR, clean ASR-like transcripts, compose the source/A/B note bundle, then publish to storage. Use `prepare` (or `process --dry-run`) when you want a no-publish run.

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
