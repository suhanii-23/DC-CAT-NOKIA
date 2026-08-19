from __future__ import annotations

from typing import TypedDict


class SpellCheckState(TypedDict, total=False):
    original_sentence: str
    corrected_sentence: str
    candidate_word: str
    suggested_word: str
    is_protected: bool
    is_valid_correction: bool
    decision: str