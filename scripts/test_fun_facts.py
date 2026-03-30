"""Test fun_facts extraction by running Step 5 on existing reviewed.json."""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from yt2notion.config import load_config
from yt2notion.models.base import ChineseContent, VideoMeta
from yt2notion.pipeline import _step_summarize


def load_workspace(ws_dir: Path) -> tuple[list[dict], VideoMeta]:
    """Load reviewed.json and metadata.json from a workspace directory."""
    with open(ws_dir / "metadata.json") as f:
        meta_raw = json.load(f)

    from yt2notion.models.base import Chapter

    chapters = [
        Chapter(title=c["title"], start_seconds=c["start_seconds"], end_seconds=c["end_seconds"])
        for c in meta_raw.get("chapters", [])
    ]

    metadata = VideoMeta(
        video_id=meta_raw["video_id"],
        title=meta_raw["title"],
        channel=meta_raw["channel"],
        upload_date=meta_raw.get("upload_date", ""),
        url=meta_raw.get("url", ""),
        duration_seconds=meta_raw.get("duration_seconds", 0),
        chapters=chapters,
        description=meta_raw.get("description", ""),
        language=meta_raw.get("language", ""),
        subtitles_available=meta_raw.get("subtitles_available", False),
        series=meta_raw.get("series", ""),
    )

    with open(ws_dir / "reviewed.json") as f:
        reviewed = json.load(f)

    return reviewed, metadata


def display_fun_facts(content: ChineseContent) -> None:
    """Pretty-print fun_facts for human review."""
    print("\n" + "=" * 60)
    print("  FUN FACTS 测试结果")
    print("=" * 60)

    if not content.fun_facts:
        print("\n  (没有提取到 fun_facts)")
        return

    labels = {
        "hot_takes": "🔥 犀利观点",
        "nerd_stats": "🤓 极客冷知识",
        "media_mentions": "📚 作品提及",
    }

    for key, label in labels.items():
        items = content.fun_facts.get(key, [])
        if not items:
            continue
        print(f"\n  {label}")
        print("  " + "-" * 40)
        for i, item in enumerate(items, 1):
            # Wrap long lines
            print(f"  {i}. {item}")
        print()

    print("=" * 60)

    # Also show overview + key_points briefly for context
    print("\n--- 概要 ---")
    print(content.overview[:200])
    print(f"\n--- 关键节点 ({len(content.key_points)} 个) ---")
    for kp in content.key_points[:3]:
        print(f"  [{kp.get('timestamp', '?')}] {kp.get('title', '?')}")
    if len(content.key_points) > 3:
        print(f"  ... ({len(content.key_points) - 3} more)")

    print(f"\n--- 标签 ---\n  {', '.join(content.tags)}")

    # Save raw markdown for debugging
    print("\n--- Raw Markdown (有趣发现 section) ---")
    import re

    section = re.search(r"##\s*有趣发现.*?(?=\n##(?!#)|\Z)", content.raw_markdown, re.DOTALL)
    if section:
        print(section.group(0))
    else:
        print("  (section not found in raw markdown)")


def main() -> None:
    ws_name = sys.argv[1] if len(sys.argv) > 1 else "benchmark_30min"
    ws_dir = Path(__file__).resolve().parent.parent / "workspace" / ws_name

    if not ws_dir.exists():
        print(f"Workspace not found: {ws_dir}")
        sys.exit(1)

    print(f"Loading workspace: {ws_name}")
    reviewed, metadata = load_workspace(ws_dir)
    print(f"  Title: {metadata.title}")
    print(f"  Segments: {len(reviewed)}")
    print(f"  Duration: {metadata.duration_seconds}s")

    config_path = str(Path(__file__).resolve().parent.parent / "config.yaml")
    config = load_config(config_path)
    raw_config = {
        "model": config.model,
        "output": config.output,
    }

    print("\nRunning Step 5 (summarize) with fun_facts extraction...")
    content = _step_summarize(reviewed, metadata, raw_config, verbose=True)

    display_fun_facts(content)

    # Save result
    output_path = ws_dir / "fun_facts_test.json"
    with open(output_path, "w") as f:
        json.dump(
            {
                "fun_facts": content.fun_facts,
                "overview": content.overview,
                "tags": content.tags,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )
    print(f"\nSaved to: {output_path}")


if __name__ == "__main__":
    main()
