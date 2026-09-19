"""Public typed product-pipeline API."""

from yt2notion.pipelines.contracts import (
    NotePipelineRequest,
    PreparedContent,
    ProcessPipelineRequest,
    ProgressCallback,
    ProgressEvent,
    StorageFactory,
    TranscribePipelineRequest,
    emit_progress,
)
from yt2notion.pipelines.notes import run_note_pipeline, run_process_pipeline
from yt2notion.pipelines.subtitle_pack import run_subtitle_pack_pipeline
from yt2notion.pipelines.transcribe import run_transcribe_pipeline
from yt2notion.pipelines.translation_experiment import run_translation_experiment_pipeline

__all__ = [
    "NotePipelineRequest",
    "PreparedContent",
    "ProcessPipelineRequest",
    "ProgressCallback",
    "ProgressEvent",
    "StorageFactory",
    "TranscribePipelineRequest",
    "emit_progress",
    "run_note_pipeline",
    "run_process_pipeline",
    "run_subtitle_pack_pipeline",
    "run_transcribe_pipeline",
    "run_translation_experiment_pipeline",
]
