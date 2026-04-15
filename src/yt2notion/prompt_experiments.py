"""Helpers for comparing summary prompt variants against an existing workspace."""

from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from yt2notion.config import load_config
from yt2notion.models import create_summarizer
from yt2notion.models.llm import create_llm_caller
from yt2notion.pipeline import (
    _download_audio,
    _download_webpage_transcript,
    _is_long_content,
    _merge_segments_into_groups,
    _step_download,
    _step_segment,
    _step_transcribe,
)
from yt2notion.process import SubtitleEntry, format_timestamped_transcript, seconds_to_display
from yt2notion.prompts import render_prompt
from yt2notion.topic_segment import segment_transcript
from yt2notion.workspace import Workspace

if TYPE_CHECKING:
    from yt2notion.config import AppConfig
    from yt2notion.models.base import ChineseContent, ChunkSummary, VideoMeta


@dataclass(frozen=True)
class PromptVariant:
    """One experimental prompt variant for long-form synthesis."""

    slug: str
    label: str
    prompt_name: str
    mode: Literal["reduce", "direct"] = "reduce"


@dataclass(frozen=True)
class VariantOutput:
    """Artifacts written for one experimental prompt variant."""

    slug: str
    label: str
    markdown_path: Path
    json_path: Path


DEFAULT_LONGFORM_VARIANTS: tuple[PromptVariant, ...] = (
    PromptVariant(
        slug="reading_guide",
        label="导读短文",
        prompt_name="synthesize_reading_guide",
    ),
    PromptVariant(
        slug="guided_notes",
        label="结构化笔记",
        prompt_name="synthesize_guided_notes",
    ),
    PromptVariant(
        slug="raw_evidence_guide",
        label="原文直读+证据锚点",
        prompt_name="summarize_long_direct_evidence",
        mode="direct",
    ),
)


def generate_workspace_summary_variants(
    *,
    workspace_dir: Path,
    config: dict,
    variants: list[PromptVariant],
) -> list[VariantOutput]:
    """Generate long-form summary variants for an existing workspace."""
    ws = Workspace(workspace_dir.parent, workspace_dir.name)
    metadata = ws.load_metadata()
    reviewed = ws.load_reviewed() or ws.load_transcripts()

    if metadata is None:
        raise FileNotFoundError(f"metadata.json not found in {workspace_dir}")
    if not reviewed:
        raise FileNotFoundError(f"reviewed.json or transcripts.json not found in {workspace_dir}")
    if not _is_long_content(metadata, reviewed, config):
        raise ValueError("Prompt comparison helper currently supports long-form workspaces only")

    summarizer = create_summarizer(config)
    chunk_summaries: list[ChunkSummary] | None = None

    outputs: list[VariantOutput] = []
    for variant in variants:
        if variant.mode == "direct":
            content = _generate_direct_markdown(
                reviewed,
                metadata,
                summarizer,
                variant.prompt_name,
            )
        else:
            if chunk_summaries is None:
                chunk_summaries = _build_chunk_summaries(reviewed, metadata, summarizer)
            content = summarizer.synthesize(
                chunk_summaries,
                metadata,
                prompt_name=variant.prompt_name,
            )
        markdown_path = workspace_dir / f"summary.{variant.slug}.md"
        json_path = workspace_dir / f"summary.{variant.slug}.json"

        markdown_path.write_text(
            _render_variant_markdown(content.raw_markdown, metadata, variant),
            encoding="utf-8",
        )
        json_path.write_text(
            json.dumps(
                {
                    "variant": asdict(variant),
                    "overview": content.overview,
                    "key_points": content.key_points,
                    "tags": content.tags,
                    "fun_facts": content.fun_facts,
                    "mindmap": content.mindmap,
                    "raw_markdown": content.raw_markdown,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        outputs.append(
            VariantOutput(
                slug=variant.slug,
                label=variant.label,
                markdown_path=markdown_path,
                json_path=json_path,
            )
        )

    manifest_path = workspace_dir / "summary.variants.json"
    manifest_path.write_text(
        json.dumps(
            {
                "workspace_dir": str(workspace_dir),
                "variants": [
                    {
                        "slug": output.slug,
                        "label": output.label,
                        "markdown_path": str(output.markdown_path),
                        "json_path": str(output.json_path),
                    }
                    for output in outputs
                ],
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    return outputs


def parse_ab_article_pair_json(text: str) -> dict[str, dict[str, str]]:
    """Parse a strict JSON object containing version_a/version_b article drafts."""
    import re

    fence_match = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.DOTALL)
    json_str = fence_match.group(1) if fence_match else text
    data = json.loads(json_str)

    result: dict[str, dict[str, str]] = {}
    for key in ("version_a", "version_b"):
        payload = data.get(key, {})
        result[key] = {
            "title": str(payload.get("title", "")).strip(),
            "markdown": str(payload.get("markdown", "")).strip(),
        }
    return result


def generate_workspace_ab_article_pair(
    *,
    workspace_dir: Path,
    config: dict,
    prompt_name: str = "article_ab_pair",
) -> dict[str, dict[str, Path]]:
    """Generate two article variants from transcript artifacts in a single LLM call."""
    ws = Workspace(workspace_dir.parent, workspace_dir.name)
    metadata = ws.load_metadata()
    reviewed = ws.load_reviewed() or ws.load_transcripts()

    if metadata is None:
        raise FileNotFoundError(f"metadata.json not found in {workspace_dir}")
    if not reviewed:
        raise FileNotFoundError(f"reviewed.json or transcripts.json not found in {workspace_dir}")

    transcript = _format_linear_transcript(reviewed)
    caller = create_llm_caller(config, model_key="translate_model")
    duration = seconds_to_display(metadata.duration_seconds)
    system_prompt = render_prompt(
        prompt_name,
        title=metadata.title,
        channel=metadata.channel,
        duration=duration,
        url=metadata.url,
    )
    user_prompt = (
        f"Video: {metadata.title} by {metadata.channel}\n"
        f"URL: {metadata.url}\n\n{transcript}"
    )
    raw = caller.call(system_prompt, user_prompt, max_tokens=8000)
    parsed = parse_ab_article_pair_json(raw)

    outputs: dict[str, dict[str, Path]] = {}
    for version_key, payload in parsed.items():
        markdown_path = workspace_dir / f"article_pair.{version_key}.md"
        json_path = workspace_dir / f"article_pair.{version_key}.json"
        markdown_path.write_text(
            _render_article_markdown(
                title=payload["title"],
                body_markdown=payload["markdown"],
                metadata=metadata,
                label=version_key,
            ),
            encoding="utf-8",
        )
        json_path.write_text(
            json.dumps(
                {
                    "version": version_key,
                    "title": payload["title"],
                    "markdown": payload["markdown"],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        outputs[version_key] = {
            "markdown_path": markdown_path,
            "json_path": json_path,
        }

    manifest_path = workspace_dir / "article_pair.manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "workspace_dir": str(workspace_dir),
                "prompt_name": prompt_name,
                "outputs": {
                    key: {
                        "markdown_path": str(value["markdown_path"]),
                        "json_path": str(value["json_path"]),
                    }
                    for key, value in outputs.items()
                },
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return outputs


def prepare_workspace_transcript_only(
    *,
    url: str,
    config: AppConfig,
    workspace_dir: str | None = None,
    verbose: bool = False,
) -> Workspace:
    """Run download/segment/transcribe only and persist transcript artifacts."""
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    metadata = _step_download(url, raw_config, verbose)
    base_dir = Path(workspace_dir or config.workspace.get("base_dir", "./workspace"))
    ws = Workspace(base_dir, metadata.video_id)

    if ws.load_transcripts() is not None:
        return ws

    ws.save_metadata(metadata)

    if metadata.subtitles_available:
        if not _download_webpage_transcript(url, metadata, ws, verbose):
            _download_audio(url, metadata, raw_config, ws, verbose)
    else:
        if not _download_webpage_transcript(url, metadata, ws, verbose):
            _download_audio(url, metadata, raw_config, ws, verbose)

    segments = _step_segment(metadata, raw_config, verbose)
    ws.save_segments(segments)
    transcripts = _step_transcribe(ws, metadata, segments, raw_config, verbose)

    source = transcripts[0].get("source", "subtitle") if transcripts else "subtitle"
    if source == "asr":
        max_seg_sec = raw_config.get("output", {}).get("max_segment_seconds", 600)
        transcripts = segment_transcript(transcripts, metadata, raw_config, max_seg_sec)

    ws.save_transcripts(transcripts)
    return ws


def _build_chunk_summaries(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: object,
) -> list[ChunkSummary]:
    groups = _merge_segments_into_groups(reviewed)
    chunk_summaries: list[ChunkSummary] = []
    for index, group in enumerate(groups):
        segment_info = {
            "segment_title": group["title"],
            "start_time": seconds_to_display(group["start_seconds"]),
            "end_time": seconds_to_display(group["end_seconds"]),
            "segment_index": str(index + 1),
            "total_segments": str(len(groups)),
        }
        chunk_summaries.append(summarizer.summarize_chunk(group["text"], metadata, segment_info))
    return chunk_summaries


def _generate_direct_markdown(
    reviewed: list[dict],
    metadata: VideoMeta,
    summarizer: object,
    prompt_name: str,
) -> ChineseContent:
    transcript = _format_reviewed_segments(reviewed)
    return summarizer.summarize_transcript_to_markdown(
        transcript,
        metadata,
        prompt_name=prompt_name,
    )


def _format_reviewed_segments(reviewed: list[dict]) -> str:
    blocks: list[str] = []
    for seg in reviewed:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        title = str(seg.get("title", "")).strip() or "Untitled segment"
        start = seconds_to_display(seg["start_seconds"])
        end = seconds_to_display(seg["end_seconds"])
        entry = SubtitleEntry(
            start_seconds=seg["start_seconds"],
            end_seconds=seg["end_seconds"],
            text=text,
        )
        transcript = format_timestamped_transcript([entry])
        blocks.append(f'[SEGMENT start={start} end={end} title="{title}"]\n{transcript}')
    return "\n\n".join(blocks)


def _format_linear_transcript(reviewed: list[dict]) -> str:
    """Flatten transcript segments into a lightly-marked long text."""
    parts: list[str] = []
    for seg in reviewed:
        text = str(seg.get("text", "")).strip()
        if not text:
            continue
        title = str(seg.get("title", "")).strip() or "Untitled segment"
        start = seconds_to_display(seg["start_seconds"])
        end = seconds_to_display(seg["end_seconds"])
        parts.append(f"[{start}-{end}] {title}\n{text}")
    return "\n\n".join(parts)


def _render_variant_markdown(raw_markdown: str, metadata: VideoMeta, variant: PromptVariant) -> str:
    header = [
        f"# Prompt Variant: {variant.label}",
        f"来源：{metadata.channel} 「{metadata.title}」",
        f"链接：{metadata.url}",
        "",
    ]
    return "\n".join(header) + raw_markdown.strip() + "\n"


def _render_article_markdown(
    *,
    title: str,
    body_markdown: str,
    metadata: VideoMeta,
    label: str,
) -> str:
    header = [
        f"# {title}",
        "",
        f"> Variant: {label}",
        f"> 来源：{metadata.channel} 「{metadata.title}」",
        f"> 链接：{metadata.url}",
        "",
    ]
    return "\n".join(header) + body_markdown.strip() + "\n"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace-dir", required=True, help="Existing workspace directory")
    parser.add_argument("--config", required=True, help="Config file used to create the summarizer")
    parser.add_argument(
        "--variant",
        action="append",
        choices=[variant.slug for variant in DEFAULT_LONGFORM_VARIANTS],
        help="Optional subset of variants to run. Repeat for multiple values.",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    app_config = load_config(args.config)
    config = {
        "model": app_config.model,
        "storage": app_config.storage,
        "extract": app_config.extract,
        "credit": app_config.credit,
        "output": app_config.output,
        "workspace": app_config.workspace,
    }
    selected = set(args.variant or [])
    variants = [
        variant
        for variant in DEFAULT_LONGFORM_VARIANTS
        if not selected or variant.slug in selected
    ]
    outputs = generate_workspace_summary_variants(
        workspace_dir=Path(args.workspace_dir),
        config=config,
        variants=variants,
    )
    for output in outputs:
        print(f"{output.label}: {output.markdown_path}")
        print(f"{output.label} JSON: {output.json_path}")


if __name__ == "__main__":
    main()
