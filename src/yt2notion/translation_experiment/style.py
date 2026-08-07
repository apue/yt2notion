"""Non-blocking style diagnostics for edited Chinese math-course prose."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yt2notion.translation_experiment.models import SourceChapter


@dataclass(frozen=True)
class StyleFinding:
    """One auditable style-policy violation in a translated chapter."""

    code: str
    chapter_id: str
    evidence: str


@dataclass(frozen=True)
class TranslationStyleEvaluation:
    """Result of advisory checks that must not replace human judgment."""

    passed: bool
    findings: tuple[StyleFinding, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable diagnostic record."""
        return asdict(self)


@dataclass(frozen=True)
class _BilingualTerm:
    source: re.Pattern[str]
    target: re.Pattern[str]
    label: str


_PATTERN_RULES: tuple[tuple[str, re.Pattern[str]], ...] = (
    (
        "symbol_pronunciation_parenthetical",
        re.compile(r"[Ωω][（(][^）)]{0,24}(?:omega|欧米伽)[）)]", re.IGNORECASE),
    ),
    (
        "chinese_technical_numeral",
        re.compile(r"[二三四五六七八九十百千万两]+\s*(?:次|个)"),
    ),
    (
        "spoken_ordinal_repetition",
        re.compile(r"第([一二三四五六七八九十\d]+)[，,、\s]+第\1(?:\s*个)?"),
    ),
    (
        "redundant_emphasis_filler",
        re.compile(r"真的\s*(?:非常)+"),
    ),
)
_COIN_CONTEXT = re.compile(r"\b(?:coin|coins|heads?|tails?|flip|flips|toss|tosses)\b", re.I)
_ASCII_COIN_OUTCOME = re.compile(r"\b[HT]{2,}\b")
_BILINGUAL_TERMS: tuple[_BilingualTerm, ...] = (
    _BilingualTerm(
        source=re.compile(r"\bmeasure theory\b", re.IGNORECASE),
        target=re.compile(r"测度论[（(]\s*measure theory\s*[）)]", re.IGNORECASE),
        label="measure theory",
    ),
)


def evaluate_translation_style(
    chapters: tuple[SourceChapter, ...], translations: dict[str, str]
) -> TranslationStyleEvaluation:
    """Find high-confidence style regressions without changing translated text."""
    findings: list[StyleFinding] = []
    for chapter in chapters:
        translation = translations.get(chapter.chapter_id, "")
        if not translation:
            continue
        for code, pattern in _PATTERN_RULES:
            match = pattern.search(translation)
            if match:
                findings.append(
                    StyleFinding(
                        code=code,
                        chapter_id=chapter.chapter_id,
                        evidence=match.group(0),
                    )
                )
        if _COIN_CONTEXT.search(chapter.source_text):
            match = _ASCII_COIN_OUTCOME.search(translation)
            if match:
                findings.append(
                    StyleFinding(
                        code="coin_outcome_not_localized",
                        chapter_id=chapter.chapter_id,
                        evidence=match.group(0),
                    )
                )
        for term in _BILINGUAL_TERMS:
            if term.source.search(chapter.source_text) and not term.target.search(translation):
                findings.append(
                    StyleFinding(
                        code="missing_bilingual_term",
                        chapter_id=chapter.chapter_id,
                        evidence=term.label,
                    )
                )
    return TranslationStyleEvaluation(passed=not findings, findings=tuple(findings))
