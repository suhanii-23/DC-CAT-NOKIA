"""Dictionary spell checking -- the non-AI counterpart to the T5 path.

Looks each word up in wordfreq's English frequency list (already a
dependency; ships its data, runs offline) and proposes the most frequent
dictionary word within a small edit distance (Norvig-style edits).

wordfreq is built from real-world text, so common misspellings ("recieve",
"teh") are in it with a low frequency. A word is therefore flagged when it is
either unknown, or rare *and* one edit away from a far more common word.
Real-word confusions ("form" for "from") are deliberately left to the T5
path -- a dictionary has no context to judge them.

Never invents evidence: a word with no close, common dictionary candidate is
not reported. An unknown word with nothing near it is far more likely a
product name or parameter than a typo.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

_LETTERS = "abcdefghijklmnopqrstuvwxyz"

# A word below this zipf score is treated as not in the dictionary.
_UNKNOWN_ZIPF = 1.0
# A known word below this score is "rare" and may be a common misspelling.
_RARE_ZIPF = 3.3
# A rare word is only flagged when its candidate is this much more common
# (zipf is log10, so 1.5 means roughly 30x more frequent).
_RARE_MARGIN = 1.5
# Suggestions must themselves be ordinary words, not other rare forms.
_MIN_SUGGESTION_ZIPF = 3.0
# A stem this common makes a regular inflection of it a real word.
_STEM_ZIPF = 2.5
# Shorter tokens are mostly abbreviations. Three-letter words are only
# corrected by swapping adjacent letters ("teh"), never by other edits.
_MIN_WORD_LENGTH = 3

# Whitespace-separated chunks. Only purely alphabetic chunks (after trimming
# punctuation) are checked: anything carrying digits, slashes, dots, @ or
# underscores is a URL, path, version, or identifier, not prose.
_CHUNK_RE = re.compile(r"\S+")
_PROSE_WORD_RE = re.compile(r"^[A-Za-z]+(?:['-][A-Za-z]+)*$")
_TRIM = "\"'()[]{}<>,;:!?.‘’“”"


@dataclass(frozen=True)
class DictionaryChange:
    original: str
    suggestion: str


class DictionaryChecker:
    """Frequency-dictionary spell checker. Loads its word list once, lazily."""

    def __init__(self) -> None:
        self._zipf: dict[str, float] | None = None

    def _ensure_vocab(self) -> dict[str, float]:
        if self._zipf is None:
            from wordfreq import get_frequency_dict

            self._zipf = {
                word: math.log10(freq) + 9
                for word, freq in get_frequency_dict("en").items()
                if word.isalpha()
            }
        return self._zipf

    def check(self, sentence: str) -> list[DictionaryChange]:
        """Return likely misspellings in ``sentence`` with one suggestion each."""
        changes: list[DictionaryChange] = []
        for chunk in _CHUNK_RE.findall(sentence):
            token = chunk.strip(_TRIM)
            if not _PROSE_WORD_RE.match(token):
                continue
            for word in re.split(r"['-]", token):
                suggestion = self.suggest(word)
                if suggestion is not None:
                    changes.append(DictionaryChange(word, _match_case(word, suggestion)))
        return changes

    def suggest(self, word: str) -> str | None:
        """Return a correction for ``word``, or None if it looks fine."""
        if len(word) < _MIN_WORD_LENGTH:
            return None
        zipf = self._ensure_vocab()
        lower = word.lower()
        score = zipf.get(lower, 0.0)
        if score >= _RARE_ZIPF:
            return None

        if len(lower) == 3:
            best = self._best(_transposes(lower))
            return best[0] if best and best[1] >= score + _RARE_MARGIN else None

        # A plural / third-person "s" ("parses", "headers"), or "-d" / "-ing"
        # on an e-final stem ("cabled", "cabling"), is a real word however
        # rare the inflected form is.
        if any(self._is_stem(stem) for stem in _regular_stems(lower)):
            return None

        if score < _UNKNOWN_ZIPF:
            # Regular suffixes on a known stem ("checkpointed") are real words
            # the frequency list simply hasn't seen.
            if any(self._is_stem(stem) for stem in _suffix_stems(lower)):
                return None
            best = self._best(_edits1(lower)) or self._best(_edits2(lower))
            return best[0] if best and not _suffix_swap(lower, best[0]) else None

        # A rare but real word that is a longer form of a common one is
        # usually an inflection ("cabled", "warms"), not a typo -- so only
        # transpositions, substitutions, and missing letters count here.
        best = self._best(_edits1(lower, deletes=False))
        if (
            best
            and best[1] >= score + _RARE_MARGIN
            and not _suffix_swap(lower, best[0])
        ):
            return best[0]
        return None

    def _is_stem(self, word: str) -> bool:
        return self._ensure_vocab().get(word, 0.0) >= _STEM_ZIPF

    def _best(self, candidates) -> tuple[str, float] | None:
        zipf = self._ensure_vocab()
        best: tuple[str, float] | None = None
        for candidate in candidates:
            score = zipf.get(candidate)
            if score is None or score < _MIN_SUGGESTION_ZIPF:
                continue
            if best is None or score > best[1]:
                best = (candidate, score)
        return best


def _transposes(word: str) -> set[str]:
    return {word[:i] + word[i + 1] + word[i] + word[i + 2:] for i in range(len(word) - 1)}


def _edits1(word: str, deletes: bool = True) -> set[str]:
    splits = [(word[:i], word[i:]) for i in range(len(word) + 1)]
    deleted = [a + b[1:] for a, b in splits if b] if deletes else []
    transposes = list(_transposes(word))
    replaces = [a + c + b[1:] for a, b in splits if b for c in _LETTERS]
    inserts = [a + c + b for a, b in splits for c in _LETTERS]
    return set(deleted + transposes + replaces + inserts)


def _edits2(word: str):
    return (e2 for e1 in _edits1(word) for e2 in _edits1(e1))


def _regular_stems(word: str) -> list[str]:
    """Stems whose regular inflection is ``word``. Deliberately excludes
    plain "-ed" ("occur" + "ed"), since the misspelling "occured" is exactly
    that shape; and "-ss" words, where the s belongs to the stem ("acess")."""
    stems = []
    if word.endswith("s") and not word.endswith("ss"):
        stems.append(word[:-1])
    if word.endswith("ed"):
        stems.append(word[:-1])  # "cabled" -> "cable"; "occured" -> "occure", unknown
    if word.endswith("ing"):
        stems.append(word[:-3] + "e")
    return stems


def _suffix_stems(word: str) -> list[str]:
    stems = []
    for suffix in ("ing", "ed", "er", "ers", "ly"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 4:
            stem = word[: -len(suffix)]
            stems += [stem, stem + "e"]
    return stems


def _suffix_swap(word: str, candidate: str) -> bool:
    """True when two long words differ only in their last two letters --
    one inflection traded for another ("automates" / "automated",
    "identifier" / "identified"), which is not a spelling fix."""
    if min(len(word), len(candidate)) < 6:
        return False
    prefix = 0
    for a, b in zip(word, candidate):
        if a != b:
            break
        prefix += 1
    if sorted(word[prefix:]) == sorted(candidate[prefix:]):
        return False  # swapped letters ("lenght"), a real typo
    return prefix >= max(len(word), len(candidate)) - 2


def _match_case(original: str, suggestion: str) -> str:
    if original.isupper():
        return suggestion.upper()
    if original[0].isupper():
        return suggestion[0].upper() + suggestion[1:]
    return suggestion
