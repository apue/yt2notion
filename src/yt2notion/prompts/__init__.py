"""Prompt template loading and rendering."""

from __future__ import annotations

from pathlib import Path

PROMPTS_DIR = Path(__file__).parent


def load_prompt(name: str) -> str:
    """Load a prompt template by name (without .md extension)."""
    path = PROMPTS_DIR / f"{name}.md"
    if not path.exists():
        raise FileNotFoundError(f"Prompt template not found: {path}")
    return path.read_text(encoding="utf-8")


def render_prompt(name: str, **kwargs: str) -> str:
    """Load and render a prompt template with variable substitution."""
    template = load_prompt(name)
    if kwargs:
        template = template.format(**kwargs)
    return template
