# yt2notion

Download YouTube or podcast media, transcribe it, compose a Chinese source/A/B
note bundle, and optionally publish the bundle to Obsidian.

## Supported commands

```bash
# Download media, extract audio, transcribe, and stop
uv run yt2notion transcribe "URL"

# Build the source/A/B bundle without publishing
uv run yt2notion prepare "URL"

# Build and publish the bundle to Obsidian
uv run yt2notion process "URL"
```

`transcribe` resolves configuration in this order:

1. explicit `--config`;
2. `~/.yt2notion/config.yaml`;
3. local `config.yaml`.

It writes `metadata.json`, downloaded media, `audio.mp3`,
`transcripts.json`, and readable `transcript.md` under the workspace.

## Installation

Requirements: Python 3.11+, `uv`, `yt-dlp`, and `ffmpeg`.

```bash
git clone https://github.com/apue/yt2notion.git
cd yt2notion
uv sync
cp config.example.yaml config.yaml
```

Use `uv sync --extra anthropic` only when `model.backend` is
`anthropic_api`.

## Provider interfaces

| Capability | Interface | Adapters |
|---|---|---|
| Media acquisition | `MediaSource` | `yt_dlp` |
| ASR | `Transcriber` | `groq`, `remote` |
| LLM call | `LLMCaller` | `claude_code`, `codex_cli`, `anthropic_api` |
| Bundle storage | `Storage` | `obsidian` |

Provider selection is explicit in `config.yaml`. Prompt assembly and response
parsing are provider-independent.

## ASR behavior

- Subtitles bypass ASR.
- Groq hourly quota errors wait and retry the same persisted chunk.
- Groq daily quota errors can switch the failed and remaining chunks to the
  configured fallback adapter.
- Completed chunks are reused when resuming from `transcribe`.
- Request errors such as `400/401/403` fail directly.

See [PROJECT_MAP.md](PROJECT_MAP.md) for pipeline and artifact contracts, and
[docs/operations/asr-service.md](docs/operations/asr-service.md) for remote ASR
operations.

## Development

```bash
uv sync --extra dev
uv run pytest tests/ -q
uv run ruff check src/yt2notion tests
uv run ruff format --check src/yt2notion tests
```

## License

MIT
