"""Deterministic quality gates for final translated text."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from yt2notion.translation_experiment.models import SourceChapter

_GREEK_SYMBOLS: dict[str, tuple[str, str]] = {
    "alpha": ("Α", "α"),
    "beta": ("Β", "β"),
    "gamma": ("Γ", "γ"),
    "delta": ("Δ", "δ"),
    "epsilon": ("Ε", "ε"),
    "zeta": ("Ζ", "ζ"),
    "eta": ("Η", "η"),
    "theta": ("Θ", "θ"),
    "iota": ("Ι", "ι"),
    "kappa": ("Κ", "κ"),
    "lambda": ("Λ", "λ"),
    "mu": ("Μ", "μ"),
    "nu": ("Ν", "ν"),
    "xi": ("Ξ", "ξ"),
    "omicron": ("Ο", "ο"),
    "pi": ("Π", "π"),
    "rho": ("Ρ", "ρ"),
    "sigma": ("Σ", "σ"),
    "tau": ("Τ", "τ"),
    "upsilon": ("Υ", "υ"),
    "phi": ("Φ", "φ"),
    "chi": ("Χ", "χ"),
    "psi": ("Ψ", "ψ"),
    "omega": ("Ω", "ω"),
}
_CASE_CUE = re.compile(
    rf"\b(big|capital|uppercase|little|small|lowercase)\s+({'|'.join(_GREEK_SYMBOLS)})\b",
    re.IGNORECASE,
)
_INTERNAL_ID = re.compile(r"\bc\d{3}(?:-b\d{3})?\b")


@dataclass(frozen=True)
class NotationExpectation:
    """A symbol required by explicit source-language evidence."""

    chapter_id: str
    source_cue: str
    symbol: str


@dataclass(frozen=True)
class FinalTextEvaluation:
    """Machine-checkable gates over the final chapter-level translation."""

    passed: bool
    expected_notation: tuple[NotationExpectation, ...]
    missing_notation: tuple[NotationExpectation, ...]
    missing_chapter_ids: tuple[str, ...]
    unexpected_chapter_ids: tuple[str, ...]
    internal_id_leaks: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable evaluation record."""
        return asdict(self)


def evaluate_final_text(
    chapters: tuple[SourceChapter, ...], translations: dict[str, str]
) -> FinalTextEvaluation:
    """Evaluate final text without scoring intermediate implementation paths."""
    expected_ids = [chapter.chapter_id for chapter in chapters]
    actual_ids = list(translations)
    missing_ids = tuple(source_id for source_id in expected_ids if source_id not in translations)
    unexpected_ids = tuple(source_id for source_id in actual_ids if source_id not in expected_ids)
    expectations = _collect_notation_expectations(chapters)
    missing_notation = tuple(
        expectation
        for expectation in expectations
        if expectation.symbol not in translations.get(expectation.chapter_id, "")
    )
    leaks = tuple(
        sorted(
            {
                match.group(0)
                for translation in translations.values()
                for match in _INTERNAL_ID.finditer(translation)
            }
        )
    )
    passed = not (missing_ids or unexpected_ids or missing_notation or leaks)
    return FinalTextEvaluation(
        passed=passed,
        expected_notation=expectations,
        missing_notation=missing_notation,
        missing_chapter_ids=missing_ids,
        unexpected_chapter_ids=unexpected_ids,
        internal_id_leaks=leaks,
    )


def _collect_notation_expectations(
    chapters: tuple[SourceChapter, ...],
) -> tuple[NotationExpectation, ...]:
    expectations: list[NotationExpectation] = []
    seen: set[tuple[str, str]] = set()
    for chapter in chapters:
        for match in _CASE_CUE.finditer(chapter.source_text):
            case_cue = match.group(1).lower()
            name = match.group(2).lower()
            uppercase, lowercase = _GREEK_SYMBOLS[name]
            symbol = uppercase if case_cue in {"big", "capital", "uppercase"} else lowercase
            key = (chapter.chapter_id, symbol)
            if key in seen:
                continue
            seen.add(key)
            expectations.append(
                NotationExpectation(
                    chapter_id=chapter.chapter_id,
                    source_cue=match.group(0),
                    symbol=symbol,
                )
            )
    return tuple(expectations)
