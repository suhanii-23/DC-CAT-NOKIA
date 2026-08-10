"""Sentence extraction and Nokia/technical-term filtering.

Reuses ``tools/terminology.py`` (the Excel-loaded allow-list + identifier-shape
rule) rather than duplicating it -- that module has no agent/graph dependency,
so importing it here keeps this feature's non-agentic and future-agentic paths
sharing one correct implementation of Nokia protection.
"""
from __future__ import annotations

import re

from .tools.terminology import TerminologyTool

_SENTENCE_RE = re.compile(r"[^.!?]+[.!?]?")


def split_sentences(text: str) -> list[str]:
    """Split paragraph text into sentences."""
    return [s.strip() for s in _SENTENCE_RE.findall(text) if s.strip()]


def is_protected_term(word: str, terminology: TerminologyTool) -> bool:
    """True if ``word`` is approved Nokia terminology or identifier-shaped
    (ALL-CAPS, contains digits/underscores, mixed-case like gNodeB)."""
    return terminology.is_protected(word)


def load_terminology(excel_path: str | None) -> TerminologyTool:
    """Load the Nokia terminology allow-list from Excel, or built-in defaults."""
    if excel_path:
        return TerminologyTool.from_excel(excel_path)
    return TerminologyTool()
