#!/usr/bin/env python3
"""Benchmark: new pipeline with topic segmentation + parallel LLM calls.

Reads existing ASR transcript from workspace/benchmark_30min/transcripts.json,
then runs: topic_segment → review (3-parallel) → summarize MAP (3-parallel) → REDUCE.
Compares timing against the old single-segment approach.
"""

from __future__ import annotations

import json
import subprocess
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

WORKSPACE = Path("workspace/benchmark_30min")
PARALLELISM = 3


def timer(label: str):
    """Simple context manager for timing."""

    class Timer:
        def __init__(self):
            self.elapsed = 0.0

        def __enter__(self):
            self.start = time.monotonic()
            return self

        def __exit__(self, *args):
            self.elapsed = time.monotonic() - self.start
            print(f"  [{label}] {self.elapsed:.2f}s")

    return Timer()


def call_claude(system_prompt: str, user_prompt: str, model: str = "haiku") -> str:
    """Call claude -p and return text result."""
    prompt = f"{system_prompt}\n\n---\n\n{user_prompt}"
    cmd = [
        "claude",
        "-p",
        "--model",
        model,
        "--max-turns",
        "1",
        "--output-format",
        "json",
    ]
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True, check=True)
    try:
        output = json.loads(result.stdout)
        return output.get("result", result.stdout).strip()
    except json.JSONDecodeError:
        return result.stdout.strip()


def step_topic_segment(full_text: str, duration_seconds: int) -> list[dict]:
    """Use Haiku to find topic boundaries in the transcript."""
    system_prompt = """You are a transcript segmentation expert. Given a full transcript, identify natural topic boundaries.

Output a JSON array of segments. Each segment has:
- "title": a short descriptive title for the topic (in English)
- "start_char": approximate character offset where this topic starts
- "summary": one sentence describing what this segment covers

Target segment length: 3-8 minutes of speech (~1500-4000 characters).
If a topic naturally spans longer, it's OK to have segments up to 5000 chars.

Output ONLY valid JSON, no markdown fences, no explanation."""

    user_prompt = f"Transcript ({duration_seconds} seconds of audio, {len(full_text)} characters):\n\n{full_text}"

    raw = call_claude(system_prompt, user_prompt, model="haiku")

    # Parse JSON from response
    # Try to find JSON array in the response
    start = raw.find("[")
    end = raw.rfind("]")
    if start >= 0 and end > start:
        segments_raw = json.loads(raw[start : end + 1])
    else:
        raise ValueError(f"Could not parse segments from LLM response: {raw[:200]}")

    # Convert to text segments
    segments = []
    for i, seg in enumerate(segments_raw):
        start_char = seg.get("start_char", 0)
        end_char = (
            segments_raw[i + 1]["start_char"] if i + 1 < len(segments_raw) else len(full_text)
        )
        text = full_text[start_char:end_char].strip()
        if text:
            segments.append(
                {
                    "title": seg.get("title", f"Part {i + 1}"),
                    "text": text,
                    "start_char": start_char,
                    "end_char": end_char,
                }
            )

    return segments


def step_review_parallel(segments: list[dict], parallelism: int) -> list[dict]:
    """Review segments in parallel using Haiku."""
    system_prompt = (
        "You are a transcript editor. Clean up the following ASR transcription segment.\n\n"
        "Context: This is from the Acquired podcast episode about Formula 1.\n\n"
        "Tasks:\n"
        "1. Fix likely ASR errors, especially proper nouns\n"
        "2. Remove filler words (you know, like, um, uh) unless they carry meaning\n"
        "3. Unify inconsistent spellings of the same term\n"
        "4. Fix obvious sentence boundary errors\n"
        "5. Preserve the original meaning exactly — do NOT summarize\n"
        "6. Keep the original language\n\n"
        "Output ONLY the cleaned transcript text."
    )

    results = [None] * len(segments)

    def review_one(i: int, seg: dict) -> tuple[int, str]:
        cleaned = call_claude(system_prompt, seg["text"], model="haiku")
        return i, cleaned

    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        futures = {pool.submit(review_one, i, seg): i for i, seg in enumerate(segments)}
        for future in as_completed(futures):
            i, cleaned = future.result()
            results[i] = {**segments[i], "text": cleaned}
            print(f"    Review [{i + 1}/{len(segments)}] done")

    return results


def step_summarize_map_parallel(segments: list[dict], parallelism: int) -> list[dict]:
    """MAP phase: summarize each segment in parallel using Sonnet."""
    system_prompt = (
        "You are a content summarizer. Summarize this transcript segment.\n\n"
        "Output a JSON object with:\n"
        '- "segment_title": descriptive title\n'
        '- "key_points": array of 2-5 key points (strings)\n'
        '- "key_terms": array of important terms/names mentioned\n'
        '- "summary": 2-3 sentence summary\n\n'
        "Output ONLY valid JSON."
    )

    results = [None] * len(segments)

    def summarize_one(i: int, seg: dict) -> tuple[int, dict]:
        raw = call_claude(system_prompt, seg["text"], model="sonnet")
        start = raw.find("{")
        end = raw.rfind("}")
        if start >= 0 and end > start:
            parsed = json.loads(raw[start : end + 1])
        else:
            parsed = {
                "segment_title": seg["title"],
                "summary": raw[:500],
                "key_points": [],
                "key_terms": [],
            }
        return i, parsed

    with ThreadPoolExecutor(max_workers=parallelism) as pool:
        futures = {pool.submit(summarize_one, i, seg): i for i, seg in enumerate(segments)}
        for future in as_completed(futures):
            i, summary = future.result()
            results[i] = summary
            print(f"    Map [{i + 1}/{len(segments)}] done")

    return results


def step_summarize_reduce(chunk_summaries: list[dict]) -> str:
    """REDUCE phase: synthesize all chunk summaries into final Chinese output."""
    system_prompt = (
        "You are a content synthesizer. Given summaries of multiple transcript segments "
        "from the Acquired podcast about Formula 1, create a unified Chinese summary.\n\n"
        "Output:\n"
        "1. 概要 (overview paragraph)\n"
        "2. 关键节点 (key points with timestamps)\n"
        "3. 思维导图 (markmap format)\n"
        "4. 标签 (tags)\n\n"
        "Write in natural Chinese, not word-for-word translation."
    )

    user_prompt = json.dumps(chunk_summaries, indent=2, ensure_ascii=False)
    return call_claude(system_prompt, user_prompt, model="opus")


def main():
    # Load existing ASR transcript
    with open(WORKSPACE / "transcripts.json") as f:
        transcripts = json.load(f)

    full_text = transcripts[0]["text"]
    print(f"Loaded transcript: {len(full_text)} chars\n")

    timings = {}

    # --- Step 1: Topic segmentation ---
    print("=== Topic Segmentation (Haiku) ===")
    with timer("topic_segment") as t:
        segments = step_topic_segment(full_text, 1800)
    timings["topic_segment"] = t.elapsed
    print(f"  → {len(segments)} segments found:")
    for i, seg in enumerate(segments):
        print(f"    [{i + 1}] {seg['title']} ({len(seg['text'])} chars)")

    # --- Step 2: Review (parallel) ---
    print(f"\n=== Review ({PARALLELISM}-parallel Haiku) ===")
    with timer("review_parallel") as t:
        reviewed = step_review_parallel(segments, PARALLELISM)
    timings["review_parallel"] = t.elapsed

    # --- Step 3: Summarize MAP (parallel) ---
    print(f"\n=== Summarize MAP ({PARALLELISM}-parallel Sonnet) ===")
    with timer("summarize_map") as t:
        chunk_summaries = step_summarize_map_parallel(reviewed, PARALLELISM)
    timings["summarize_map"] = t.elapsed

    # --- Step 4: Summarize REDUCE ---
    print("\n=== Summarize REDUCE (Opus) ===")
    with timer("summarize_reduce") as t:
        final = step_summarize_reduce(chunk_summaries)
    timings["summarize_reduce"] = t.elapsed

    timings["total_post_asr"] = sum(timings.values())

    # --- Results ---
    print("\n\n" + "=" * 60)
    print("TIMING COMPARISON (post-ASR stages only)")
    print("=" * 60)

    old_timings = {
        "review": 120.1,
        "summarize_map": 21.7,
        "summarize_reduce": 23.9,
        "total_post_asr": 165.7,
    }

    print(f"\n{'Step':<25} {'Old (1-seg serial)':<20} {'New (multi-seg parallel)':<20}")
    print("-" * 65)
    print(f"{'Topic segment':<25} {'N/A':<20} {timings['topic_segment']:.1f}s")
    print(f"{'Review':<25} {old_timings['review']:.1f}s{'':<13} {timings['review_parallel']:.1f}s")
    print(
        f"{'Summarize MAP':<25} {old_timings['summarize_map']:.1f}s{'':<13} {timings['summarize_map']:.1f}s"
    )
    print(
        f"{'Summarize REDUCE':<25} {old_timings['summarize_reduce']:.1f}s{'':<13} {timings['summarize_reduce']:.1f}s"
    )
    print("-" * 65)
    print(
        f"{'TOTAL (post-ASR)':<25} {old_timings['total_post_asr']:.1f}s{'':<13} {timings['total_post_asr']:.1f}s"
    )

    speedup = (
        old_timings["total_post_asr"] / timings["total_post_asr"]
        if timings["total_post_asr"] > 0
        else 0
    )
    print(f"\nSpeedup: {speedup:.2f}x")

    # Save detailed results
    results_path = WORKSPACE / "benchmark_new_pipeline.json"
    results_path.write_text(
        json.dumps(
            {
                "timings": timings,
                "old_timings": old_timings,
                "segments_count": len(segments),
                "parallelism": PARALLELISM,
                "segments": [{"title": s["title"], "chars": len(s["text"])} for s in segments],
            },
            indent=2,
            ensure_ascii=False,
        )
    )
    print(f"\nDetailed results saved to {results_path}")


if __name__ == "__main__":
    main()
