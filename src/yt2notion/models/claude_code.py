"""Claude Code (-p mode) LLM backend. Uses CC subscription, zero API cost."""

from __future__ import annotations

# TODO: Implement ClaudeCodeModel
# - __init__(summarize_model="sonnet", translate_model="opus")
# - summarize(): pipe transcript to `claude -p --model sonnet --max-turns 1`
# - to_chinese(): pipe summary JSON to `claude -p --model opus --max-turns 1`
# - Load prompts from src/yt2notion/prompts/
# - Parse JSON from claude -p --output-format json (content in "result" field)
