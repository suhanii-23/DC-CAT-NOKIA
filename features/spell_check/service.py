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

from common.contracts import Document, FeatureResult, Finding

from .model import get_model
from .preprocessing import is_protected_term, load_terminology, split_sentences
from .utils import word_level_changes

logger = logging.getLogger(__name__)


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
            for para in document.paragraphs:
                for sentence in split_sentences(para.text):
                    corrected = self._model.correct(sentence)
                    for change in word_level_changes(sentence, corrected):
                        if is_protected_term(change.original, self._terminology):
                            continue
                        findings.append(_to_finding(
                            self.name, change, sentence, corrected, para.page, para.index
                        ))
            return FeatureResult(feature=self.name, status="ok", findings=findings)
        except Exception as exc:  # process() must never raise
            logger.exception("spell_check failed")
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        return [
            "incorrect_word", "suggested_correction", "issue_type",
            "original_sentence", "corrected_sentence", "paragraph_index",
        ]


def _to_finding(feature, change, sentence, corrected, page, paragraph_index) -> Finding:
    return Finding(
        feature=feature,
        severity="warning",
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
