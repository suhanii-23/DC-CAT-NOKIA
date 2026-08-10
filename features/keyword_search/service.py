"""Keyword search — lexical occurrence counting plus BGE/FAISS semantic search.

Two passes, in this order:

  1. LEXICAL (always runs, no dependencies). Case-insensitive whole-token
     counting with per-unit snippets. Authoritative: never suppressed,
     never replaced by semantic results.
  2. SEMANTIC (runs whenever its dependencies and the local model are
     available). BAAI/bge-base-en-v1.5 embeddings searched with a FAISS
     IndexFlatIP, returning up to 5 additional passages that are related
     to the query without containing it verbatim — e.g. "login" finding a
     paragraph that talks about authentication.

If the semantic dependencies or the model are unavailable, the lexical
result is still returned with status="ok" and the reason is recorded in
FeatureResult.meta["semantic"]. is_available() therefore always returns
True: returning False would make the CLI skip the whole feature and take
lexical search down with it.

Findings layout:
  findings[0]  lexical aggregate for the document (match_type="lexical_summary")
               — present whenever there is at least one lexical hit
  findings[1:] lexical per-unit findings (match_type="lexical"), then
               semantic findings (match_type="semantic")

Counting unit: paragraphs when the document has them, pages otherwise.
Never both — common.parser derives paragraphs *from* page text, so
counting both would double-count every match. Paragraphs are preferred
because they preserve locality for DOCX, where every page number is 1.

Note on the parsed structure: common.contracts.Page has no `paragraphs`
attribute. Document.paragraphs is a flat list and each Paragraph carries
its own `page` back-reference, so that is how paragraphs are consumed
here. The contract is frozen and is not modified by this feature.

Model provisioning (manual, out of band — nothing is ever downloaded at
runtime):

    1. On a machine with network access, fetch BAAI/bge-base-en-v1.5.
    2. Copy the resulting folder to  models/bge-base-en-v1.5/  in the repo
       root, or anywhere you like and point DCCAT_BGE_MODEL_PATH at it.
    3. models/ is gitignored; weights are never committed.

If that directory is absent, semantic search is reported unavailable and
lexical search carries on unaffected.
"""
from __future__ import annotations

import os
import re
from collections.abc import Mapping
from typing import NamedTuple, Optional

from common.contracts import Document, FeatureResult, Finding

_SNIPPET_RADIUS = 60

_MATCH_TYPE_SUMMARY = "lexical_summary"
_MATCH_TYPE_UNIT = "lexical"
_MATCH_TYPE_SEMANTIC = "semantic"

# --- semantic configuration -------------------------------------------

_EMBEDDING_DIM = 768  # BAAI/bge-base-en-v1.5
_DEFAULT_MODEL_DIRNAME = "bge-base-en-v1.5"

# BGE v1.5 is an asymmetric retrieval model: the *query* carries this
# instruction prefix, passages are embedded bare. Dropping it measurably
# degrades ranking.
_QUERY_PREFIX = "Represent this sentence for searching relevant passages: "

_CHUNK_MAX_CHARS = 400
_SEMANTIC_TOP_K = 5  # semantic findings actually returned
_SEMANTIC_OVERFETCH = 10  # candidates pulled from FAISS before dedupe

# Deliberately disabled. A similarity floor cannot be chosen honestly
# without calibrating against real documents, and BGE cosine scores sit in
# a narrow band that makes a borrowed constant meaningless. Scores are
# recorded on every semantic finding so a threshold can be calibrated
# later; until then nothing is filtered by score.
_SEMANTIC_THRESHOLD: Optional[float] = None

_REPO_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+")


class _Unit(NamedTuple):
    """One searchable span of the document."""

    text: str
    page: int
    paragraph_index: Optional[int]


class _UnitHit(NamedTuple):
    unit: _Unit
    occurrences: int
    snippet: str


class _Chunk(NamedTuple):
    """An embedding-sized span, with full provenance back to the document."""

    text: str
    page: int
    paragraph_index: Optional[int]
    chunk_index: int
    char_start: int


class KeywordSearchService:
    name = "keyword_search"

    def __init__(self) -> None:
        # Lazy: the model is loaded at most once per instance, on first
        # use. app/cli.py builds one instance at import time and reuses it
        # across every document in a folder walk, so a failed load is
        # cached too — otherwise every document would retry it.
        self._model = None
        self._model_error: Optional[str] = None
        self._model_load_attempted = False

    def is_available(self) -> bool:
        # Always True: lexical search needs nothing. Semantic degrades on
        # its own and reports why in meta["semantic"].
        return True

    def supports(self, document: Document) -> bool:
        return True

    def process(self, document: Document, options: Optional[dict] = None) -> FeatureResult:
        try:
            query = _extract_query(options)
            if not query:
                return FeatureResult(feature=self.name, status="ok", findings=[])

            pattern = _query_pattern(query)

            # --- lexical pass (authoritative, always runs) ---
            hits = _find_hits(document, pattern)
            occurrences = sum(hit.occurrences for hit in hits)
            pages = sorted({hit.unit.page for hit in hits})

            findings: list[Finding] = []
            if occurrences:
                findings.append(
                    _summary_finding(self.name, query, occurrences, pages, hits)
                )
                findings += [_unit_finding(self.name, query, hit) for hit in hits]

            meta = {"query": query, "occurrences": occurrences, "pages": pages}

            # --- semantic pass (additive, never suppresses the above) ---
            semantic_findings, semantic_note = self._semantic_pass(
                document, query, pattern
            )
            findings += semantic_findings
            meta["semantic"] = semantic_note

            return FeatureResult(
                feature=self.name, status="ok", findings=findings, meta=meta
            )
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        # Must stay in sync with every key written into Finding.details;
        # tests/test_keyword_search.py enforces that.
        return [
            "query",
            "match_type",
            "occurrences",
            "pages",
            "snippet",
            "paragraph_index",
            "score",
            "chunk_index",
        ]

    # --- semantic internals --------------------------------------------

    def _ensure_model(self):
        """Load the local BGE model once per instance, or record why not.

        Never downloads: the model is resolved from a local directory and
        loaded with local_files_only=True. A Hugging Face model id is
        never used as a fallback.
        """
        if self._model is not None:
            return self._model
        if self._model_load_attempted:
            return None
        self._model_load_attempted = True

        # Belt and braces: no hub traffic, no telemetry, even if some
        # dependency would otherwise try.
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
        os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
        os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")

        try:
            from sentence_transformers import SentenceTransformer
        except Exception as exc:
            self._model_error = f"unavailable: sentence-transformers not importable ({exc})"
            return None

        path = _model_path()
        if not os.path.isdir(path):
            self._model_error = (
                f"unavailable: no local model directory at {path!r}; "
                "provision the weights manually or set DCCAT_BGE_MODEL_PATH"
            )
            return None

        try:
            self._model = SentenceTransformer(path, local_files_only=True)
        except Exception as exc:
            self._model_error = f"unavailable: model failed to load ({exc})"
            self._model = None
            return None

        return self._model

    def _semantic_pass(
        self, document: Document, query: str, pattern: re.Pattern
    ) -> tuple[list[Finding], str]:
        """Return (findings, note). Never raises: any problem degrades to
        no semantic findings plus a reason for meta["semantic"]."""
        try:
            model = self._ensure_model()
            if model is None:
                return [], self._model_error or "unavailable: model not loaded"

            try:
                import faiss
                import numpy as np
            except Exception as exc:
                return [], f"unavailable: numpy/faiss not importable ({exc})"

            chunks = _chunks(document)
            if not chunks:
                return [], "ok: no chunks to search"

            passages = model.encode(
                [chunk.text for chunk in chunks],
                normalize_embeddings=True,
                convert_to_numpy=True,
                batch_size=16,
            )
            query_vector = model.encode(
                [_QUERY_PREFIX + query],
                normalize_embeddings=True,
                convert_to_numpy=True,
            )

            # FAISS requires float32, C-contiguous input. Normalized
            # vectors make inner product identical to cosine similarity.
            passages = np.ascontiguousarray(passages, dtype="float32")
            query_vector = np.ascontiguousarray(query_vector, dtype="float32")

            # Guards against the wrong model being provisioned: bge-small
            # would silently produce 384-dim vectors here.
            if passages.shape[1] != _EMBEDDING_DIM:
                return [], (
                    f"unavailable: expected {_EMBEDDING_DIM}-dim embeddings "
                    f"({_DEFAULT_MODEL_DIRNAME}), got {passages.shape[1]}"
                )

            index = faiss.IndexFlatIP(passages.shape[1])
            index.add(passages)

            k = min(_SEMANTIC_OVERFETCH, index.ntotal)
            scores, ids = index.search(query_vector, k)

            # FAISS pads with -1 when k exceeds the number of vectors.
            candidates = [
                (float(score), chunks[idx])
                for score, idx in zip(scores[0], ids[0])
                if idx >= 0
            ]

            selected = _select_semantic(candidates, pattern, _SEMANTIC_TOP_K)
            findings = [
                _semantic_finding(self.name, query, score, chunk)
                for score, chunk in selected
            ]
            return findings, f"ok: {len(findings)} result(s) from {len(chunks)} chunk(s)"
        except Exception as exc:
            return [], f"unavailable: semantic search failed ({exc})"


# --- query handling ----------------------------------------------------


def _extract_query(options: Optional[dict]) -> str:
    """Pull the query out of options, rejecting malformed input loudly.

    A missing/None/blank query is a normal "nothing to search for" and
    yields "". A wrongly-typed one is a caller bug, so it raises and
    process() converts it into status="failed" with a clear message
    rather than silently reporting zero hits.
    """
    if options is None:
        return ""
    if not isinstance(options, Mapping):
        raise TypeError(f"options must be a mapping, got {type(options).__name__}")

    raw = options.get("query")
    if raw is None:
        return ""
    if not isinstance(raw, str):
        raise TypeError(f"query must be a string, got {type(raw).__name__}")
    return raw.strip()


def _query_pattern(query: str) -> re.Pattern:
    """Case-insensitive whole-token match, tolerant of line breaks.

    Each whitespace-separated token is escaped and rejoined with \\s+, so
    a phrase still matches when the extracted text wrapped it across a
    line ("configuration\\nworkflow"). Lookarounds rather than \\b so
    queries whose edges aren't word characters (e.g. "ERR#01") match
    instead of never matching.
    """
    tokens = [re.escape(token) for token in query.split()]
    body = r"\s+".join(tokens)
    return re.compile(rf"(?<!\w){body}(?!\w)", re.IGNORECASE)


# --- document units and lexical matching -------------------------------


def _units(document: Document) -> list[_Unit]:
    """The spans to search: paragraphs if available, else pages.

    Never both — see the module docstring on double-counting. Paragraphs
    are read from the flat Document.paragraphs list (Page has no
    `paragraphs` attribute), each carrying its own page back-reference.
    """
    if document.paragraphs:
        return [_Unit(p.text, p.page, p.index) for p in document.paragraphs]
    return [_Unit(page.text, page.number, None) for page in document.pages]


def _find_hits(document: Document, pattern: re.Pattern) -> list[_UnitHit]:
    hits: list[_UnitHit] = []
    for unit in _units(document):
        matches = list(pattern.finditer(unit.text))
        if not matches:
            continue
        hits.append(
            _UnitHit(
                unit=unit,
                occurrences=len(matches),
                snippet=_snippet(unit.text, matches[0]),
            )
        )
    return hits


# --- chunking ----------------------------------------------------------


def _sentence_spans(text: str) -> list[tuple[int, int]]:
    """(start, end) offsets of sentence-ish spans, blank ones dropped."""
    spans: list[tuple[int, int]] = []
    start = 0
    for match in _SENTENCE_SPLIT_RE.finditer(text):
        spans.append((start, match.start()))
        start = match.end()
    if start < len(text):
        spans.append((start, len(text)))
    return [(s, e) for s, e in spans if text[s:e].strip()]


def _split_oversized(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Hard-split a span that is longer than one chunk, on whitespace.

    A PDF page with no sentence punctuation would otherwise become a
    single span far past the model's 512-token window and be silently
    truncated.
    """
    pieces: list[tuple[int, int]] = []
    cursor = start
    while cursor < end:
        stop = min(cursor + _CHUNK_MAX_CHARS, end)
        if stop < end:
            breakpoint_ = text.rfind(" ", cursor, stop)
            if breakpoint_ > cursor:
                stop = breakpoint_
        pieces.append((cursor, stop))
        cursor = stop + 1 if stop < end and text[stop : stop + 1] == " " else stop
    return [(s, e) for s, e in pieces if text[s:e].strip()]


def _chunk_unit(unit: _Unit) -> list[tuple[str, int]]:
    """Pack a unit's sentences into (text, char_start) chunks.

    Greedy packing up to _CHUNK_MAX_CHARS with one sentence of overlap
    between consecutive chunks, so a match near a boundary is not lost.
    """
    spans: list[tuple[int, int]] = []
    for start, end in _sentence_spans(unit.text):
        if end - start <= _CHUNK_MAX_CHARS:
            spans.append((start, end))
        else:
            spans.extend(_split_oversized(unit.text, start, end))

    chunks: list[tuple[str, int]] = []
    current: list[tuple[int, int]] = []
    for span in spans:
        if current and (span[1] - current[0][0]) > _CHUNK_MAX_CHARS:
            chunks.append(_emit_chunk(unit.text, current))
            # Carry one sentence of overlap so a match straddling a
            # boundary is not lost — but only when it still fits, or the
            # chunk would grow past the budget and be truncated by the
            # model instead.
            previous = current[-1]
            current = [previous] if (span[1] - previous[0]) <= _CHUNK_MAX_CHARS else []
        current.append(span)
    if current:
        chunks.append(_emit_chunk(unit.text, current))
    return chunks


def _emit_chunk(text: str, spans: list[tuple[int, int]]) -> tuple[str, int]:
    start, end = spans[0][0], spans[-1][1]
    return text[start:end], start


def _chunks(document: Document) -> list[_Chunk]:
    """Embedding-sized chunks over the whole document, in reading order."""
    out: list[_Chunk] = []
    for unit in _units(document):
        for chunk_text, char_start in _chunk_unit(unit):
            out.append(
                _Chunk(
                    text=chunk_text,
                    page=unit.page,
                    paragraph_index=unit.paragraph_index,
                    chunk_index=len(out),
                    char_start=char_start,
                )
            )
    return out


# --- semantic selection (pure; no numpy/faiss needed) ------------------


def _select_semantic(
    candidates: list[tuple[float, _Chunk]], pattern: re.Pattern, limit: int
) -> list[tuple[float, _Chunk]]:
    """Drop chunks already covered by an exact lexical match, order
    deterministically, and cap the result.

    Deduplication only ever removes *semantic* candidates — a chunk that
    literally contains the query is already reported by the lexical pass,
    so repeating it adds nothing. Ordering is score descending, then page,
    then chunk_index, so ties are resolved deterministically rather than
    by whatever order the index returned.
    """
    kept = [
        (score, chunk)
        for score, chunk in candidates
        if not pattern.search(chunk.text)
        and (_SEMANTIC_THRESHOLD is None or score >= _SEMANTIC_THRESHOLD)
    ]
    kept.sort(key=lambda item: (-item[0], item[1].page, item[1].chunk_index))
    return kept[:limit]


# --- finding construction ----------------------------------------------


def _summary_finding(
    feature: str, query: str, occurrences: int, pages: list[int], hits: list[_UnitHit]
) -> Finding:
    page_list = ", ".join(str(page) for page in pages)
    return Finding(
        feature=feature,
        severity="info",
        page=pages[0],
        message=f"{query!r} found {occurrences} time(s) on page(s) {page_list}",
        confidence=None,
        details={
            "query": query,
            "match_type": _MATCH_TYPE_SUMMARY,
            "occurrences": occurrences,
            "pages": pages,
            "snippet": hits[0].snippet,
            "paragraph_index": None,
            "score": None,
            "chunk_index": None,
        },
    )


def _unit_finding(feature: str, query: str, hit: _UnitHit) -> Finding:
    where = f"page {hit.unit.page}"
    if hit.unit.paragraph_index is not None:
        where += f", paragraph {hit.unit.paragraph_index}"
    return Finding(
        feature=feature,
        severity="info",
        page=hit.unit.page,
        message=f"{query!r} found {hit.occurrences} time(s) on {where}",
        confidence=None,
        details={
            "query": query,
            "match_type": _MATCH_TYPE_UNIT,
            "occurrences": hit.occurrences,
            "pages": [hit.unit.page],
            "snippet": hit.snippet,
            "paragraph_index": hit.unit.paragraph_index,
            "score": None,
            "chunk_index": None,
        },
    )


def _semantic_finding(feature: str, query: str, score: float, chunk: _Chunk) -> Finding:
    where = f"page {chunk.page}"
    if chunk.paragraph_index is not None:
        where += f", paragraph {chunk.paragraph_index}"
    return Finding(
        feature=feature,
        severity="info",
        page=chunk.page,
        message=(
            f"Passage related to {query!r} on {where} "
            f"(similarity {score:.3f}, no exact match)"
        ),
        confidence=score,
        details={
            "query": query,
            "match_type": _MATCH_TYPE_SEMANTIC,
            # Semantic matches are not occurrences of the query — the
            # whole point is that the query does not appear verbatim.
            "occurrences": 0,
            "pages": [chunk.page],
            # Verbatim document text. Never generated, never paraphrased.
            "snippet": " ".join(chunk.text.split()),
            "paragraph_index": chunk.paragraph_index,
            "score": score,
            "chunk_index": chunk.chunk_index,
        },
    )


def _snippet(text: str, match: re.Match) -> str:
    start = max(0, match.start() - _SNIPPET_RADIUS)
    end = min(len(text), match.end() + _SNIPPET_RADIUS)
    fragment = " ".join(text[start:end].split())
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{fragment}{suffix}"


def _model_path() -> str:
    """Local model directory. Never a Hugging Face model identifier."""
    configured = os.environ.get("DCCAT_BGE_MODEL_PATH")
    if configured:
        return configured
    return os.path.join(_REPO_ROOT, "models", _DEFAULT_MODEL_DIRNAME)
