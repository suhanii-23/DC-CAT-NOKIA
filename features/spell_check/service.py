"""Spell check — terminology allow-list + difflib real-word confusion check.

Two things work today without any model:
  1. A Nokia/telecom terminology allow-list that is never flagged.
  2. A difflib-based check against a small set of commonly confused
     real-word pairs (e.g. "form" vs "from").

A T5-based grammar/spell model is a planned upgrade for broader coverage
— see the TODO in _ensure_model below. It is not wired into process() yet.
"""
from __future__ import annotations

import difflib
import re
from typing import Optional

from common.contracts import Document, Finding, FeatureResult

# Terms that must never be flagged, regardless of case.
ALLOW_LIST = {
    "gnodeb",
    "mocn",
    "rsrp",
    "x2",
    "err#01",
    "airscale_rnc",
}

# word -> the word it's most often confused with, in technical writing.
CONFUSABLE_PAIRS: dict[str, str] = {
    "form": "from",
    "their": "there",
    "then": "than",
    "loose": "lose",
    "affect": "effect",
    "principal": "principle",
    "complement": "compliment",
}

# The "correct" side of each pair — never flag these as if they were typos
# of the "wrong" side (e.g. don't flag "from" as a typo of "form").
_CORRECTION_TARGETS = set(CONFUSABLE_PAIRS.values())

# Everyday words that sit one edit away from a confusable word (e.g. "for"
# vs "form", "the" vs "then"). Without this guard, the difflib fuzzy check
# below would flag ordinary function words as typos. The fuzzy check exists
# to catch actual misspellings of the confusable words themselves, not to
# second-guess unrelated common words.
_COMMON_WORDS = {
    "the", "a", "an", "and", "or", "but", "nor", "so", "yet", "for", "to", "of",
    "in", "on", "at", "is", "was", "are", "were", "be", "been", "being", "it",
    "its", "this", "that", "these", "those", "as", "by", "not", "no", "if",
    "with", "from", "he", "she", "they", "we", "you", "i", "do", "does", "did",
    "has", "have", "had", "will", "would", "can", "could", "should", "may",
    "might", "must", "who", "what", "when", "where", "why", "how", "all",
    "any", "each", "other", "such", "only", "own", "same", "than", "too",
    "very", "just", "about", "into", "over", "after", "before", "between",
    "see", "used", "during",
}

_WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_#']*")
_CONTEXT_RADIUS = 30
_CLOSE_MATCH_CUTOFF = 0.86
_MIN_FUZZY_WORD_LENGTH = 5


class SpellCheckService:
    name = "spell_check"

    def __init__(self) -> None:
        self._model = None  # lazily loaded; see _ensure_model

    def is_available(self) -> bool:
        return True

    def supports(self, document: Document) -> bool:
        return True

    def _ensure_model(self):
        """Lazily load the grammar/spell-correction model, once per instance.

        TODO: add a T5 grammar-correction pass for broader coverage, e.g.:

            if self._model is None:
                from transformers import T5ForConditionalGeneration, T5Tokenizer
                self._model = T5ForConditionalGeneration.from_pretrained(
                    "path/to/local-t5-grammar-checkpoint"
                )
            return self._model

        Not called from process() yet — the allow-list and difflib checks
        below don't need it.
        """
        return self._model

    def process(self, document: Document, options: Optional[dict] = None) -> FeatureResult:
        try:
            findings: list[Finding] = []
            for paragraph in document.paragraphs:
                for match in _WORD_RE.finditer(paragraph.text):
                    word = match.group(0)
                    suggestion = _check_word(word)
                    if suggestion is None:
                        continue
                    findings.append(
                        Finding(
                            feature=self.name,
                            severity="warning",
                            page=paragraph.page,
                            message=f"Possible real-word error: {word!r} (did you mean {suggestion!r}?)",
                            details={
                                "word": word,
                                "suggestion": suggestion,
                                "context": _make_context(
                                    paragraph.text, match.start(), match.end()
                                ),
                            },
                        )
                    )

            return FeatureResult(feature=self.name, status="ok", findings=findings)
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        return ["word", "suggestion", "context"]


def _check_word(word: str) -> Optional[str]:
    lower = word.lower()
    if lower in ALLOW_LIST:
        return None
    if lower in CONFUSABLE_PAIRS:
        return CONFUSABLE_PAIRS[lower]
    if lower in _COMMON_WORDS or lower in _CORRECTION_TARGETS:
        return None
    if len(lower) < _MIN_FUZZY_WORD_LENGTH:
        return None

    close = difflib.get_close_matches(
        lower, CONFUSABLE_PAIRS.keys(), n=1, cutoff=_CLOSE_MATCH_CUTOFF
    )
    if close:
        return CONFUSABLE_PAIRS[close[0]]
    return None


def _make_context(text: str, start: int, end: int) -> str:
    lo = max(0, start - _CONTEXT_RADIUS)
    hi = min(len(text), end + _CONTEXT_RADIUS)
    context = text[lo:hi].replace("\n", " ").strip()
    prefix = "..." if lo > 0 else ""
    suffix = "..." if hi < len(text) else ""
    return f"{prefix}{context}{suffix}"
