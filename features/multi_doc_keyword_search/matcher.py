"""Literal keyword matching for multi-document keyword search.

Pure functions: no I/O, no model, no state. Deliberately independent of
features/keyword_search/ — that feature is frozen, and duplicating a
short regex is cheaper than coupling two features whose matching
semantics are allowed to diverge.

Matching rules:

  - **Literal.** Only the characters the user supplied are searched for.
    No stemming, no synonyms, no query expansion, no fuzzy matching, no
    embeddings, no model of any kind. The user's keyword is the source
    of truth.
  - **Case-insensitive.** "authentication" matches "Authentication",
    "AUTHENTICATION" and "AuThEnTiCaTiOn".
  - **Whole-word.** "authentication" does not match "preauthentication"
    or "authentications". Lookarounds rather than \b, so a keyword whose
    edges are not word characters ("ERR#01") still matches instead of
    never matching.
  - **Whitespace-tolerant.** A multi-word keyword still matches when the
    extracted text wrapped it across a line break ("configuration\nworkflow").
"""
from __future__ import annotations

import re
from typing import NamedTuple

# Characters of surrounding text kept on each side of a match.
CONTEXT_RADIUS = 60


class EmptyKeywordError(ValueError):
    """Raised when the keyword is missing or only whitespace.

    An empty keyword is a validation error, not a search for everything.
    """


class Occurrence(NamedTuple):
    """One literal match inside a single span of text."""

    text: str  # the matched text exactly as it appears in the document
    start: int  # character offset of the match within the span
    end: int
    context: str  # whitespace-collapsed surrounding text, with ellipses


def normalise_keyword(keyword: object) -> str:
    """Validate and trim the user's keyword.

    A wrongly-typed keyword is a caller bug and raises TypeError; a
    blank one raises EmptyKeywordError. Callers at the API boundary turn
    both into a readable failed result rather than letting them escape.
    """
    if keyword is None:
        raise EmptyKeywordError("keyword must not be empty")
    if not isinstance(keyword, str):
        raise TypeError(f"keyword must be a string, got {type(keyword).__name__}")
    trimmed = keyword.strip()
    if not trimmed:
        raise EmptyKeywordError("keyword must not be empty")
    return trimmed


def compile_keyword(keyword: str) -> re.Pattern:
    """Compile the keyword into a case-insensitive whole-word pattern.

    Compiled once per search and reused across every document — the
    keyword never changes mid-search.
    """
    tokens = [re.escape(token) for token in keyword.split()]
    body = r"\s+".join(tokens)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


def find_occurrences(
    text: str, pattern: re.Pattern, radius: int = CONTEXT_RADIUS
) -> list[Occurrence]:
    """Every occurrence of the pattern in one span, in reading order."""
    return [
        Occurrence(
            text=match.group(0),
            start=match.start(),
            end=match.end(),
            context=context_for(text, match.start(), match.end(), radius),
        )
        for match in pattern.finditer(text)
    ]


def context_for(text: str, start: int, end: int, radius: int = CONTEXT_RADIUS) -> str:
    """Verbatim surrounding text, whitespace-collapsed, ellipsed at cuts.

    Never paraphrased or generated — this is document text as extracted.
    """
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    fragment = " ".join(text[left:right].split())
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{fragment}{suffix}"
