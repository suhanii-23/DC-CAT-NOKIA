"""Spell Check feature -- minimal working pipeline (agentic layer pending
Nokia's approved LLM infrastructure decision).

Document -> paragraphs -> sentence extraction -> Nokia/identifier filtering
-> T5 contextual correction -> difflib word-level diff -> Finding.

Implements the FeatureModule contract. Uses only document.paragraphs (the
existing Document object) -- never parses PDF/DOCX itself. process() never
raises: any failure returns status="failed" with the message.

Extensibility note: model.py, preprocessing.py, and utils.py are small,
independently testable components on purpose, so an agentic/verification
layer can be added later (Candidate -> Agent -> local tools -> verification
-> Finding) without rewriting this file -- it would slot in between
preprocessing and Finding creation. The agent/mcp/memory/ subpackages already
in this folder are exactly that future layer, built and tested earlier;
they're intentionally not wired in here until Nokia confirms approved
LLM infrastructure.
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional
from wordfreq import zipf_frequency

from common.contracts import Document, FeatureResult, Finding

from .model import get_model
from .preprocessing import is_protected_term, load_terminology, split_sentences
from .utils import word_level_changes
logger = logging.getLogger(__name__)
_COMMON_WORD_THRESHOLD = 4.0


def _is_verified_spelling_change(original: str, suggestion: str) -> bool:
    """Reject changes where both words are common English words."""
    original_frequency = zipf_frequency(original.lower(), "en")
    suggestion_frequency = zipf_frequency(suggestion.lower(), "en")

def _is_verified_spelling_change(original: str, suggestion: str) -> bool:
    """Reject common-word changes unless they look like a likely typo."""
    original_frequency = zipf_frequency(original.lower(), "en")
    suggestion_frequency = zipf_frequency(suggestion.lower(), "en")

    if (
        original_frequency >= _COMMON_WORD_THRESHOLD
        and suggestion_frequency >= _COMMON_WORD_THRESHOLD
    ):
        # If both are common words, only allow a likely typo pattern.
        if len(original) != len(suggestion):
            return False

        original_lower = original.lower()
        suggestion_lower = suggestion.lower()

        differences = [
            index
            for index, (left, right) in enumerate(
                zip(original_lower, suggestion_lower)
            )
            if left != right
        ]

        # Allow a simple adjacent-character transposition:
        # form -> from
        if len(differences) == 2:
            first, second = differences
            if (
                second == first + 1
                and original_lower[first] == suggestion_lower[second]
                and original_lower[second] == suggestion_lower[first]
            ):
                return True

        # Otherwise, two common valid words should not be treated
        # as a spelling correction.
        return False

    return True
class SpellCheckService:
    name = "spell_check"

    def __init__(self, terms_excel: Optional[str] = None) -> None:
        terms_path = terms_excel or os.environ.get("NOKIA_TERMS_XLSX")
        self._terminology = load_terminology(terms_path)
        self._model = get_model()  # lazy: no weights loaded until first correct()

    def is_available(self) -> bool:
        return True

    def supports(self, document: Document) -> bool:
        return document.format in ("pdf", "docx")

    def process(
        self, document: Document, options: Optional[dict[str, Any]] = None
    ) -> FeatureResult:
        try:
            findings: list[Finding] = []

            sentence_items = []

            for para in document.paragraphs:
                for sentence in split_sentences(para.text):
                    sentence_items.append(
                        (sentence, para.page, para.index)
                    )

            sentences = [item[0] for item in sentence_items]
            corrected_sentences = self._model.correct_many(
                sentences,
                batch_size=52,
            )

            for (sentence, page, paragraph_index), corrected in zip(
                sentence_items,
                corrected_sentences,
            ):
                for change in word_level_changes(sentence, corrected):
                    if not _is_verified_spelling_change(
                        change.original,
                        change.suggestion,
                    ):
                        continue

                    protected = is_protected_term(
                        change.original,
                        self._terminology,
                    )
                    if protected:
                        continue

                    findings.append(
                        _to_finding(
                            self.name,
                            change,
                            sentence,
                            corrected,
                            page,
                            paragraph_index,
                        )
                    )

            return FeatureResult(
                feature=self.name,
                status="ok",
                findings=findings,
            )

        except Exception as exc:
            logger.exception("SpellCheckService.process failed")
            return FeatureResult(
                feature=self.name,
                status="failed",
                error=str(exc),
            )


    def report_columns(self) -> list[str]:
        return [
            "incorrect_word", "suggested_correction", "issue_type",
            "original_sentence", "corrected_sentence", "paragraph_index",
        ]


def _to_finding(feature, change, sentence, corrected, page, paragraph_index) -> Finding:
    return Finding(
    feature=feature,
    page=page,
    message=f"Possible spelling error: {change.original!r} -> "
            f"{change.suggestion!r}",
    confidence=None,
    details={
            "word": change.original,
            "suggestion": change.suggestion,
            "incorrect_word": change.original,
            "suggested_correction": change.suggestion,
            "issue_type": "contextual_spelling",
            "original_sentence": sentence,
            "corrected_sentence": corrected,
            "paragraph_index": paragraph_index,
        },
    )
