"""T5 contextual correction — the one model this feature uses.

``correct(sentence)`` returns a corrected sentence. The model is loaded
exactly once via :func:`_ensure_model` (never per-sentence, never per-call) —
call :func:`get_model` to get the shared instance.

Falls back to a small, curated confusion-pair map when transformers/torch
aren't installed or the weights aren't available (e.g. no network to
huggingface.co). This keeps the demo working today; swap in real weights by
setting ``NOKIA_SPELLCHECK_T5_MODEL`` once the benchmark says which size to use
(see the README/benchmark script — this must be run on real hardware, not
faked here).
"""
from __future__ import annotations

import logging
import os
import re

logger = logging.getLogger(__name__)

_DEFAULT_MODEL_NAME = "vennify/t5-base-grammar-correction"

# Curated real-word confusions common in technical documentation. Used when no
# T5 weights are loaded. Conservative and directional by design — it only
# fires on known confusions, never invents corrections.
_CONFUSIONS: dict[str, str] = {
    "form": "from", "thier": "their", "teh": "the",
    "recieve": "receive", "recieved": "received", "occured": "occurred",
    "seperate": "separate", "definately": "definitely",
    "paramter": "parameter", "paramters": "parameters",
}
# Only correct these when local context indicates the confusion is likely,
# to avoid false positives on legitimate uses of the word.
_CONTEXT_SENSITIVE = {
    "form": {
        "before": {"retrieved", "read", "copied", "taken", "derived",
                   "obtained", "loaded", "extracted", "sent", "removed",
                   "returned", "came", "come", "differ", "apart"},
        "after": {"the", "a", "an", "this", "that", "these", "those",
                  "oss", "database", "server", "system"},
    },
}
_WORD_RE = re.compile(r"[A-Za-z]+")


class T5CorrectionModel:
    """Wraps a T5 grammar-correction model with lazy loading."""

    def __init__(self, model_name: str | None = None) -> None:
        self._model_name = model_name or os.environ.get(
            "NOKIA_SPELLCHECK_T5_MODEL", _DEFAULT_MODEL_NAME
        )
        self._tokenizer = None
        self._model = None
        self._load_attempted = False

    def _ensure_model(self) -> bool:
        """Load the model once. Returns True if a real model is available."""
        if self._load_attempted:
            return self._model is not None
        self._load_attempted = True
        try:
            from transformers import T5ForConditionalGeneration, T5Tokenizer

            logger.info("Loading T5 model %s (once)...", self._model_name)
            self._tokenizer = T5Tokenizer.from_pretrained(self._model_name)
            self._model = T5ForConditionalGeneration.from_pretrained(self._model_name)
            self._model.eval()
            logger.info("T5 model loaded.")
            return True
        except Exception as exc:
            logger.warning(
                "T5 model unavailable (%s); using deterministic fallback. "
                "Run the benchmark script and set up transformers+torch to "
                "enable real contextual correction.", exc
            )
            return False

    def correct(self, sentence: str) -> str:
        """Return a corrected version of ``sentence``.

        Never raises: on any model failure, falls back to the confusion-map
        correction (which may be a no-op if nothing matches).
        """
        if self._ensure_model():
            try:
                ids = self._tokenizer(
                    "Fix spelling errors only. Do not change grammar, wording, plurality, punctuation, or meaning: " + sentence, return_tensors="pt"
                ).input_ids
                out = self._model.generate(ids, max_length=128)
                return self._tokenizer.decode(out[0], skip_special_tokens=True)
            except Exception as exc:
                logger.warning("T5 inference failed on a sentence: %s", exc)
        return _fallback_correct(sentence)


def _fallback_correct(sentence: str) -> str:
    tokens = _WORD_RE.findall(sentence)
    lower = [t.lower() for t in tokens]
    result = sentence
    for i, tok in enumerate(lower):
        target = _CONFUSIONS.get(tok)
        if target is None:
            continue
        if tok in _CONTEXT_SENSITIVE and not _context_supports(lower, i, tok):
            continue
        result = re.sub(rf"\b{re.escape(tokens[i])}\b", target, result, count=1)
    return result


def _context_supports(lower: list[str], i: int, tok: str) -> bool:
    rule = _CONTEXT_SENSITIVE[tok]
    before = lower[i - 1] if i > 0 else ""
    after = lower[i + 1] if i + 1 < len(lower) else ""
    return before in rule["before"] or after in rule["after"]


_shared_model: T5CorrectionModel | None = None


def get_model() -> T5CorrectionModel:
    """Return the process-wide shared model instance, creating it once."""
    global _shared_model
    if _shared_model is None:
        _shared_model = T5CorrectionModel()
    return _shared_model
