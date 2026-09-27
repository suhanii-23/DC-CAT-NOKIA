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
  - **Hyphenation-tolerant.** A word the typesetter split across two lines
    still matches: "em-" + line break + "bedded", and words carrying soft
    hyphens (U+00AD), which real PDFs contain in large numbers (1,699
    line-end soft hyphens in one 570-page textbook). A soft hyphen counts
    as part of the word, so "develop" does not match inside a soft-
    hyphenated "developments".

The matched text and the context are tidied for reading. The match is
shown as one word ("embedded", never "em-bedded"). The context loses its
soft hyphens and the line break after a visible hyphen, and its whitespace
is collapsed. Nothing else changes — the context is still document text,
never paraphrased or generated.
"""
from __future__ import annotations

import re
from typing import NamedTuple, Optional

# Characters kept on each side of a match when the enclosing sentence is
# too long to show whole, or has no sentence punctuation nearby.
CONTEXT_RADIUS = 80

# The enclosing sentence is shown whole when it is at most this long.
MAX_SENTENCE = 250

_SOFT_HYPHEN = "\u00ad"

# What may sit between two letters of one word in extracted text: a hyphen
# followed by a line break, or a soft hyphen with or without one.
_BREAK = r"(?:[\u00ad\u2010-][ \t]*\r?\n\s*|\u00ad)"
_OPTIONAL_BREAK = _BREAK + "?"

# The same breaks, located inside a matched word so they can be removed.
_BREAK_RE = re.compile(rf"(?<=\w){_BREAK}(?=\w)")

# A soft hyphen is only ever a hyphenation point, so it goes together with
# any line break after it.
_SOFT_HYPHEN_RE = re.compile(r"\u00ad\s*")

# A visible hyphen at a line end inside context. It stays, because it may
# be a real compound ("sensor-based"); only the line break goes.
_HYPHEN_LINE_END_RE = re.compile(r"(?<=\w)([\u2010-])[ \t]*\r?\n\s*(?=\w)")

# End of a sentence: terminal punctuation (plus any closing quote or
# bracket) followed by whitespace, or a blank line.
_SENTENCE_BREAK_RE = re.compile(r"[.!?][\"')\]\u201d\u2019]*\s+|\n[ \t]*\n")


class EmptyKeywordError(ValueError):
    """Raised when the keyword is missing or only whitespace.

    An empty keyword is a validation error, not a search for everything.
    """


class Occurrence(NamedTuple):
    """One literal match inside a single span of text."""

    text: str  # the matched word as it reads in the document (casing kept)
    start: int  # character offset of the match within the span
    end: int
    context: str  # the surrounding sentence, or a window with ellipses


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
    tokens = [_token_pattern(token) for token in keyword.split()]
    body = r"\s+".join(tokens)
    # A soft hyphen is invisible inside a word, so the whole-word edges
    # treat it as a word character.
    edge = rf"[\w{_SOFT_HYPHEN}]"
    return re.compile(rf"(?<!{edge}){body}(?!{edge})", re.IGNORECASE)


def _token_pattern(token: str) -> str:
    """One keyword token, allowing a hyphenation break between letters."""
    parts: list[str] = []
    for position, char in enumerate(token):
        if position and char.isalnum() and token[position - 1].isalnum():
            parts.append(_OPTIONAL_BREAK)
        parts.append(re.escape(char))
    return "".join(parts)


def find_occurrences(
    text: str, pattern: re.Pattern, radius: int = CONTEXT_RADIUS
) -> list[Occurrence]:
    """Every occurrence of the pattern in one span, in reading order."""
    return [
        Occurrence(
            text=_tidy_match(match.group(0)),
            start=match.start(),
            end=match.end(),
            context=context_for(text, match.start(), match.end(), radius),
        )
        for match in pattern.finditer(text)
    ]


def context_for(text: str, start: int, end: int, radius: int = CONTEXT_RADIUS) -> str:
    """The sentence around a match, or a word-trimmed window if that is too long.

    The sentence runs from the previous sentence break to the next one.
    When it is longer than MAX_SENTENCE, or its edges are not nearby,
    `radius` characters are kept on each side instead, trimmed to whole
    words, with "..." wherever text was cut.
    """
    sentence = _sentence_bounds(text, start, end)
    if sentence is not None:
        left, right = sentence
        return _tidy_context(text[left:right])

    left = max(0, start - radius)
    right = min(len(text), end + radius)
    # Drop a word cut in half at either edge.
    if left > 0 and text[left - 1].isalnum():
        while left < start and not text[left].isspace():
            left += 1
    if right < len(text) and text[right].isalnum():
        while right > end and not text[right - 1].isspace():
            right -= 1
    prefix = "..." if left > 0 else ""
    suffix = "..." if right < len(text) else ""
    return f"{prefix}{_tidy_context(text[left:right])}{suffix}"


def _sentence_bounds(text: str, start: int, end: int) -> Optional[tuple[int, int]]:
    """(left, right) of the sentence holding text[start:end], or None.

    None when either edge lies more than MAX_SENTENCE away, so a page of
    unpunctuated table text never turns into one enormous "sentence".
    """
    search_from = max(0, start - MAX_SENTENCE)
    left = 0 if search_from == 0 else None
    for found in _SENTENCE_BREAK_RE.finditer(text, search_from, start):
        left = found.end()
    if left is None:
        return None

    search_to = min(len(text), end + MAX_SENTENCE)
    found = _SENTENCE_BREAK_RE.search(text, end, search_to)
    if found is not None:
        right = found.start() + len(found.group(0).rstrip())
    elif search_to == len(text):
        right = len(text)
    else:
        return None

    if right - left > MAX_SENTENCE:
        return None
    return left, right


def _tidy_match(fragment: str) -> str:
    """A matched keyword as one word: hyphenation breaks removed."""
    fragment = _BREAK_RE.sub("", fragment).replace(_SOFT_HYPHEN, "")
    return " ".join(fragment.split())


def _tidy_context(fragment: str) -> str:
    """Context for reading: soft hyphens gone, hyphen line breaks joined."""
    fragment = _SOFT_HYPHEN_RE.sub("", fragment)
    fragment = _HYPHEN_LINE_END_RE.sub(r"\1", fragment)
    return " ".join(fragment.split())
