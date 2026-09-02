"""Word-level diff between an original and a T5-corrected sentence.

Turns a corrected sentence into precise findings instead of reporting the
whole sentence as an error.
"""
from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_WORD_RE = re.compile(r"[A-Za-z]+")


@dataclass(frozen=True)
class WordChange:
    original: str
    suggestion: str


def _edit_distance(a: str, b: str) -> int:
    """Return the minimum number of single-character edits between two words."""
    a = a.lower()
    b = b.lower()

    if len(a) < len(b):
        a, b = b, a

    previous = list(range(len(b) + 1))

    for i, char_a in enumerate(a, start=1):
        current = [i]

        for j, char_b in enumerate(b, start=1):
            insert = current[j - 1] + 1
            delete = previous[j] + 1
            replace = previous[j - 1] + (char_a != char_b)

            current.append(min(insert, delete, replace))

        previous = current

    return previous[-1]


def _is_likely_spelling_change(original: str, suggestion: str) -> bool:
    """Keep small spelling changes and reject large T5 rewrites."""
    distance = _edit_distance(original, suggestion)

    if len(original) <= 3:
        return distance <= 1

    return distance <= 2


def word_level_changes(original: str, corrected: str) -> list[WordChange]:
    """Return single-word substitutions between ``original`` and ``corrected``."""
    if original == corrected:
        return []

    o_words = _WORD_RE.findall(original)
    c_words = _WORD_RE.findall(corrected)

    matcher = difflib.SequenceMatcher(
        a=[w.lower() for w in o_words],
        b=[w.lower() for w in c_words],
    )

    changes: list[WordChange] = []

    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for oi, cj in zip(range(i1, i2), range(j1, j2)):
                if o_words[oi].lower() != c_words[cj].lower():
                    if _is_likely_spelling_change(
                        o_words[oi],
                        c_words[cj],
                    ):
                        changes.append(
                            WordChange(
                                original=o_words[oi],
                                suggestion=c_words[cj],
                            )
                        )

    return changes