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


def word_level_changes(original: str, corrected: str) -> list[WordChange]:
    """Return single-word substitutions between ``original`` and ``corrected``."""
    if original == corrected:
        return []
    o_words = _WORD_RE.findall(original)
    c_words = _WORD_RE.findall(corrected)
    matcher = difflib.SequenceMatcher(
        a=[w.lower() for w in o_words], b=[w.lower() for w in c_words]
    )
    changes: list[WordChange] = []
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag == "replace" and (i2 - i1) == (j2 - j1):
            for oi, cj in zip(range(i1, i2), range(j1, j2)):
                if o_words[oi].lower() != c_words[cj].lower():
                    changes.append(WordChange(original=o_words[oi],
                                              suggestion=c_words[cj]))
    return changes
