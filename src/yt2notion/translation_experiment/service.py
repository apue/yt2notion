"""Translation experiment orchestration."""

from __future__ import annotations

from time import perf_counter
from typing import TYPE_CHECKING

from yt2notion.models.llm import create_llm_caller
from yt2notion.translation_experiment.artifacts import (
    load_candidate_checkpoint,
    save_candidate_checkpoint,
    source_fingerprint,
    write_experiment_artifacts,
    write_source_artifact,
)
from yt2notion.translation_experiment.generator import TranslationGenerator
from yt2notion.translation_experiment.models import TranslationExperimentResult
from yt2notion.translation_experiment.source import build_source_chapters

if TYPE_CHECKING:
    from yt2notion.models.base import VideoMeta
    from yt2notion.models.llm import LLMCaller
    from yt2notion.workspace import Workspace


class TranslationExperimentRunner:
    """Run both strategies and persist a reproducible blind-review package."""

    def __init__(self, caller: LLMCaller, *, model_label: str) -> None:
        self.generator = TranslationGenerator(caller)
        self.model_label = model_label

    def run(
        self, metadata: VideoMeta, transcripts: list[dict], workspace: Workspace
    ) -> TranslationExperimentResult:
        """Execute the controlled experiment against canonical transcripts."""
        started = perf_counter()
        chapters = build_source_chapters(transcripts)
        experiment_dir = workspace.dir / "translation_experiment"
        fingerprint = source_fingerprint(chapters)
        write_source_artifact(experiment_dir, chapters, fingerprint)

        whole_path = experiment_dir / "candidate_whole_chapter.json"
        whole_ids = [chapter.chapter_id for chapter in chapters]
        whole_checkpoint = load_candidate_checkpoint(
            whole_path,
            strategy="whole_chapter",
            fingerprint=fingerprint,
            expected_ids=whole_ids,
        )
        reused_whole = whole_checkpoint is not None

        whole_started = perf_counter()
        if whole_checkpoint is None:
            whole = self.generator.translate_whole_chapters(chapters)
            whole_generation_seconds = perf_counter() - whole_started
            save_candidate_checkpoint(
                whole_path,
                strategy="whole_chapter",
                fingerprint=fingerprint,
                items=whole,
                generation_seconds=whole_generation_seconds,
            )
        else:
            whole = whole_checkpoint.items
            whole_generation_seconds = whole_checkpoint.generation_seconds
        whole_seconds = perf_counter() - whole_started

        blocks_path = experiment_dir / "candidate_semantic_blocks.json"
        block_ids = [block.block_id for chapter in chapters for block in chapter.blocks]
        blocks_checkpoint = load_candidate_checkpoint(
            blocks_path,
            strategy="semantic_blocks",
            fingerprint=fingerprint,
            expected_ids=block_ids,
        )
        reused_blocks = blocks_checkpoint is not None
        blocks_started = perf_counter()
        if blocks_checkpoint is None:
            blocks = self.generator.translate_semantic_blocks(chapters)
            blocks_generation_seconds = perf_counter() - blocks_started
            save_candidate_checkpoint(
                blocks_path,
                strategy="semantic_blocks",
                fingerprint=fingerprint,
                items=blocks,
                generation_seconds=blocks_generation_seconds,
            )
        else:
            blocks = blocks_checkpoint.items
            blocks_generation_seconds = blocks_checkpoint.generation_seconds
        blocks_seconds = perf_counter() - blocks_started

        timings = {
            "whole_chapter": round(whole_seconds, 3),
            "semantic_blocks": round(blocks_seconds, 3),
            "experiment_total": round(perf_counter() - started, 3),
        }
        blind_review, answer_key, manifest = write_experiment_artifacts(
            output_dir=experiment_dir,
            metadata=metadata,
            chapters=chapters,
            whole=whole,
            blocks=blocks,
            model_label=self.model_label,
            timings_seconds=timings,
            generation_timings_seconds={
                "whole_chapter": round(whole_generation_seconds, 3),
                "semantic_blocks": round(blocks_generation_seconds, 3),
            },
            reused_checkpoints={
                "whole_chapter": reused_whole,
                "semantic_blocks": reused_blocks,
            },
        )
        return TranslationExperimentResult(
            workspace_dir=workspace.dir,
            experiment_dir=experiment_dir,
            blind_review_path=blind_review,
            answer_key_path=answer_key,
            manifest_path=manifest,
            timings_seconds=timings,
        )


def create_translation_experiment_runner(config: dict) -> TranslationExperimentRunner:
    """Create the experiment runner from the standard translation-model role."""
    model_config = config["model"]
    caller = create_llm_caller(config, model_key="translate_model")
    model_label = f"{model_config['backend']}:{model_config['translate_model']}"
    return TranslationExperimentRunner(caller, model_label=model_label)
