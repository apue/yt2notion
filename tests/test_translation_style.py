"""Regression tests derived from human translation-style feedback."""

from __future__ import annotations

from yt2notion.translation_experiment.source import build_source_chapters
from yt2notion.translation_experiment.style import evaluate_translation_style


def _chapter(source_text: str):
    return build_source_chapters(
        [
            {
                "title": "Style case",
                "start_seconds": 0,
                "end_seconds": 30,
                "text": source_text,
                "source": "manual_subtitle",
            }
        ]
    )


def test_style_evaluation_accepts_edited_chinese_math_prose() -> None:
    chapters = _chapter(
        "For three coin flips the outcomes include HHH and HHT. "
        "Third, the third property leads into measure theory."
    )

    result = evaluate_translation_style(
        chapters,
        {
            "c001": (
                "对于 3 次抛硬币，结果包括正正正和正正反。"
                "第 3 个性质将引出测度论（measure theory）。"
            )
        },
    )

    assert result.passed is True
    assert result.findings == ()


def test_style_evaluation_reports_each_human_feedback_pattern() -> None:
    chapters = _chapter(
        "For three coin flips the outcomes include HHH and HHT. "
        "Third, the third property leads into measure theory."
    )

    result = evaluate_translation_style(
        chapters,
        {
            "c001": (
                "对于三次抛硬币，结果包括 HHH 和 HHT。"
                "第三，第三个性质真的非常重要。"
                "用 Ω（大写 omega）表示样本空间，并引出测度论。"
            )
        },
    )

    assert result.passed is False
    assert {finding.code for finding in result.findings} == {
        "chinese_technical_numeral",
        "coin_outcome_not_localized",
        "spoken_ordinal_repetition",
        "redundant_emphasis_filler",
        "symbol_pronunciation_parenthetical",
        "missing_bilingual_term",
    }


def test_coin_outcome_check_is_context_aware() -> None:
    chapters = _chapter("Let H and T be two abstract matrices.")

    result = evaluate_translation_style(chapters, {"c001": "设 HHH 和 HHT 是两个抽象编码。"})

    assert "coin_outcome_not_localized" not in {finding.code for finding in result.findings}
