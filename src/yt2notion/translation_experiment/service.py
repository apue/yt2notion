"""Translation experiment orchestration."""

from __future__ import annotations

from collections.abc import Callable, Sequence
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
from yt2notion.translation_experiment.models import (
    CandidateIdentity,
    CanonicalTranscript,
    TranslationExperimentResult,
    TranslationItem,
    TranslationStrategy,
)
from yt2notion.translation_experiment.source import build_source_chapters

if TYPE_CHECKING:
    from pathlib import Path

    from yt2notion.config import AppConfig
    from yt2notion.models.base import VideoMeta
    from yt2notion.models.llm import LLMCaller
    from yt2notion.workspace import Workspace


class TranslationExperimentRunner:
    """Run both strategies and persist a reproducible blind-review package."""

    def __init__(self, caller: LLMCaller, *, model_label: str) -> None:
        self.generator = TranslationGenerator(caller)
        self.model_label = model_label

    def run(
        self,
        metadata: VideoMeta,
        transcripts: Sequence[CanonicalTranscript],
        workspace: Workspace,
    ) -> TranslationExperimentResult:
        """Execute the controlled experiment against canonical transcripts."""
        started = perf_counter()
        chapters = build_source_chapters(transcripts)
        experiment_dir = workspace.dir / "translation_experiment"
        fingerprint = source_fingerprint(chapters)
        write_source_artifact(experiment_dir, chapters, fingerprint)

        whole_path = experiment_dir / "candidate_whole_chapter.json"
        whole_ids = [chapter.chapter_id for chapter in chapters]
        whole, reused_whole, whole_seconds, whole_generation_seconds = (
            self._load_or_generate_candidate(
                path=whole_path,
                identity=self._identity(fingerprint, "whole_chapter"),
                expected_ids=whole_ids,
                generate=lambda: self.generator.translate_whole_chapters(chapters),
            )
        )

        blocks_path = experiment_dir / "candidate_semantic_blocks.json"
        block_ids = [block.block_id for chapter in chapters for block in chapter.blocks]
        blocks, reused_blocks, blocks_seconds, blocks_generation_seconds = (
            self._load_or_generate_candidate(
                path=blocks_path,
                identity=self._identity(fingerprint, "semantic_blocks"),
                expected_ids=block_ids,
                generate=lambda: self.generator.translate_semantic_blocks(chapters),
            )
        )

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

    def _identity(self, fingerprint: str, strategy: TranslationStrategy) -> CandidateIdentity:
        return CandidateIdentity(
            source_sha256=fingerprint,
            strategy=strategy,
            model_label=self.model_label,
            prompt_sha256=self.generator.prompt_fingerprint(strategy),
        )

    def _load_or_generate_candidate(
        self,
        *,
        path: Path,
        identity: CandidateIdentity,
        expected_ids: list[str],
        generate: Callable[[], tuple[TranslationItem, ...]],
    ) -> tuple[tuple[TranslationItem, ...], bool, float, float]:
        started = perf_counter()
        checkpoint = load_candidate_checkpoint(
            path,
            identity=identity,
            expected_ids=expected_ids,
        )
        if checkpoint is not None:
            return checkpoint.items, True, perf_counter() - started, checkpoint.generation_seconds

        items = generate()
        generation_seconds = perf_counter() - started
        save_candidate_checkpoint(
            path,
            identity=identity,
            items=items,
            generation_seconds=generation_seconds,
        )
        return items, False, generation_seconds, generation_seconds


def create_translation_experiment_runner(config: AppConfig) -> TranslationExperimentRunner:
    """Create the experiment runner from the standard translation-model role."""
    model_config = config.model
    raw_config = {
        "extract": config.extract,
        "model": config.model,
        "storage": config.storage,
        "credit": config.credit,
        "output": config.output,
    }
    caller = create_llm_caller(raw_config, model_key="translate_model")
    model_label = f"{model_config['backend']}:{model_config['translate_model']}"
    return TranslationExperimentRunner(caller, model_label=model_label)
