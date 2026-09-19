"""Application service for producing browser-consumable subtitle packages."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import asdict
from typing import TYPE_CHECKING

from yt2notion.runtime import RuntimeObserver
from yt2notion.subtitle_pack.artifacts import fingerprint, write_json, write_subtitle_artifacts
from yt2notion.subtitle_pack.models import SubtitlePackResult
from yt2notion.subtitle_pack.source import build_source_cues
from yt2notion.subtitle_pack.validation import validate_bilingual, validate_source_cues
from yt2notion.subtitle_pack.workflow import SubtitleLLMWorkflow

if TYPE_CHECKING:
    from yt2notion.models.llm import LLMCaller
    from yt2notion.transcript_artifacts import MediaTranscribeResult

SCHEMA_VERSION = 1


class SubtitlePackService:
    """Orchestrate source recovery, LLM workflow, validation, and artifact writes."""

    def __init__(
        self,
        caller: LLMCaller,
        *,
        model_label: str,
        target_language: str,
        progress_callback: Callable[[str], None] | None = None,
    ) -> None:
        self.target_language = target_language
        self.progress_callback = progress_callback
        self.workflow = SubtitleLLMWorkflow(
            caller,
            schema_version=SCHEMA_VERSION,
            model_label=model_label,
            target_language=target_language,
            progress_callback=progress_callback,
        )

    def run(self, transcription: MediaTranscribeResult) -> SubtitlePackResult:
        """Generate a browser-consumable bilingual package from local transcription artifacts."""
        ws = transcription.workspace
        profile = RuntimeObserver(
            ws.dir,
            run_name="subtitle_pack",
            inherited_timings=transcription.timings_seconds,
        )
        error: BaseException | None = None
        try:
            self._progress("Subtitle pack: building source cues")
            with profile.span("node", "build_source_cues"):
                source_kind, cues = build_source_cues(transcription)
                validate_source_cues(cues)
                write_json(ws.dir / "source_cues.json", [asdict(cue) for cue in cues])
            self._progress(f"Subtitle pack: {len(cues)} source cues ({source_kind})")

            source_fingerprint = fingerprint([asdict(cue) for cue in cues])
            self._progress("Subtitle pack: building bounded global context")
            with profile.span("node", "build_context"):
                context = self.workflow.build_context(
                    transcription.metadata,
                    cues,
                    ws.dir,
                    source_fingerprint,
                    profile,
                )
                context_fingerprint = fingerprint(context)
                write_json(
                    ws.dir / "subtitle_context.json",
                    {
                        "schema_version": SCHEMA_VERSION,
                        "source_sha256": source_fingerprint,
                        "context_sha256": context_fingerprint,
                        **context,
                    },
                )

            self._progress("Subtitle pack: correcting and translating cue batches")
            with profile.span("node", "generate_batches"):
                generated = self.workflow.generate_all(
                    cues,
                    source_kind,
                    context,
                    context_fingerprint,
                    ws.dir,
                    profile,
                )

            self._progress("Subtitle pack: running semantic quality checks")
            with profile.span("node", "semantic_quality"):
                semantic_issues = self.workflow.semantic_quality(generated, context, profile)
            if semantic_issues:
                self._progress(f"Subtitle pack: repairing {len(semantic_issues)} semantic issue(s)")
                with profile.span("node", "repair"):
                    generated = self.workflow.repair_issues(
                        generated,
                        semantic_issues,
                        source_kind,
                        context,
                        profile,
                    )
                with profile.span("node", "semantic_quality_after_repair"):
                    semantic_issues = self.workflow.semantic_quality(
                        generated,
                        context,
                        profile,
                        operation="semantic_quality_after_repair",
                    )

            self._progress("Subtitle pack: validating and writing artifacts")
            with profile.span("node", "validate_and_write"):
                report = validate_bilingual(
                    cues,
                    generated,
                    semantic_issues,
                    schema_version=SCHEMA_VERSION,
                )
                if source_kind != "manual_subtitle":
                    write_json(
                        ws.dir / "reviewed_cues.json",
                        [{"id": cue.id, "source_text": cue.source_text} for cue in generated],
                    )
                package = {
                    "schema_version": SCHEMA_VERSION,
                    "video": {
                        "id": transcription.metadata.video_id,
                        "title": transcription.metadata.title,
                        "channel": transcription.metadata.channel,
                        "url": transcription.metadata.url,
                    },
                    "source_language": transcription.metadata.language or "und",
                    "target_language": self.target_language,
                    "source_kind": source_kind,
                    "context_fingerprint": context_fingerprint,
                    "quality": {
                        "passed": report["passed"],
                        "semantic_issue_count": len(semantic_issues),
                    },
                    "cues": [asdict(cue) for cue in generated],
                }
                package_path, srt_path, report_path = write_subtitle_artifacts(
                    ws.dir,
                    package,
                    report,
                    generated,
                )
            self._progress(f"Subtitle pack: complete ({package_path})")
        except BaseException as exc:
            error = exc
            raise
        finally:
            profile_path = profile.finish(error=error)

        return SubtitlePackResult(
            workspace_dir=ws.dir,
            package_path=package_path,
            srt_path=srt_path,
            context_path=ws.dir / "subtitle_context.json",
            quality_report_path=report_path,
            profile_path=profile_path,
            cue_count=len(generated),
            source_kind=source_kind,
            quality_passed=bool(report["passed"]),
        )

    def _progress(self, message: str) -> None:
        if self.progress_callback is not None:
            self.progress_callback(message)
