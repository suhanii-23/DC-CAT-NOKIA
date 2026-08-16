"""Regression tests for the audited keyword_search defects (KS-1..KS-5).

Most of these fail on the pre-fix implementation (the KS-1 starvation cases,
the cache tests, the KS-4 truncation cases). The rest pin invariants the
fixes must not break — lexical output, report_columns coverage, and the
threshold staying off by default. They are kept separate from
tests/test_keyword_search_semantic.py so the original suite stays untouched
and it is obvious which coverage exists because of a real bug.

Tiering matches the existing semantic tests: most run on a fake encoder and
need no model weights, so they stay meaningful on a machine that has not
provisioned BGE.
"""
from __future__ import annotations

import importlib
import importlib.util
import os

import pytest

from common.contracts import Document, Finding, Page, Paragraph

service_module = importlib.import_module("features.keyword_search.service")
KeywordSearchService = getattr(service_module, "KeywordSearchService", None)

pytestmark = pytest.mark.skipif(
    KeywordSearchService is None, reason="keyword_search not implemented yet"
)

_QUERY_PREFIX = service_module._QUERY_PREFIX


def _docx_doc(paragraph_texts: list[str], path: str = "d.docx") -> Document:
    return Document(
        path=path,
        format="docx",
        page_count=1,
        pages=[Page(number=1, text="\n".join(paragraph_texts))],
        paragraphs=[
            Paragraph(text=t, page=1, index=i) for i, t in enumerate(paragraph_texts)
        ],
    )


class _CountingFakeModel:
    """Fake encoder that records how often passages were embedded.

    Same scoring scheme as the fake model in test_keyword_search_semantic.py
    (shared vocabulary -> one-hot dimension), plus a counter so the embedding
    cache can be observed. Query encodes are counted separately because they
    are expected on every call; only passage encodes should be cached.
    """

    VOCAB = ("authentication", "login", "credentials", "database")

    def __init__(self) -> None:
        self.passage_encode_calls = 0
        self.query_encode_calls = 0

    def encode(self, texts, normalize_embeddings=False, convert_to_numpy=True,
               batch_size=None):
        import numpy as np

        if len(texts) == 1 and texts[0].startswith(_QUERY_PREFIX):
            self.query_encode_calls += 1
        else:
            self.passage_encode_calls += 1

        dim = service_module._EMBEDDING_DIM
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = [0.0] * dim
            for position, word in enumerate(self.VOCAB):
                if word in lowered:
                    vector[position] = 1.0
            if not any(vector):
                vector[len(self.VOCAB)] = 1.0
            vectors.append(vector)
        array = np.array(vectors, dtype="float32")
        if normalize_embeddings:
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            array = array / np.maximum(norms, 1e-12)
        return array


def _service_with(model):
    pytest.importorskip("numpy")
    pytest.importorskip("faiss")
    service = KeywordSearchService()
    service._model = model
    service._model_load_attempted = True
    return service


def _semantic(result):
    return [f for f in result.findings if f.details["match_type"] == "semantic"]


# === KS-1: semantic candidate starvation =============================
# Pre-fix: k = min(_SEMANTIC_OVERFETCH, ntotal) spent the whole candidate
# budget on chunks that _select_semantic then discarded for containing the
# query, so any document with >= _SEMANTIC_OVERFETCH lexical matches
# returned zero semantic results while still reporting status="ok".

RELATED = "Users supply credentials at the sign-in step of the procedure."


def _doc_with_lexical_noise(n_lexical: int) -> Document:
    paragraphs = [
        f"The authentication step {i} is described in this section."
        for i in range(n_lexical)
    ]
    paragraphs.append(RELATED)
    return _docx_doc(paragraphs)


@pytest.mark.parametrize("n_lexical", [9, 10, 11, 30, 60])
def test_semantic_survives_many_lexical_matches(n_lexical):
    """The measured cliff was at exactly _SEMANTIC_OVERFETCH (10)."""
    service = _service_with(_CountingFakeModel())
    result = service.process(_doc_with_lexical_noise(n_lexical), {"query": "authentication"})

    semantic = _semantic(result)
    assert semantic, f"no semantic results with {n_lexical} lexical matches"
    assert any(RELATED in f.details["snippet"] for f in semantic)


def test_candidate_budget_grows_past_the_lexical_matches():
    """Guards the specific arithmetic, so a future edit can't silently
    reintroduce a fixed cap."""
    service = _service_with(_CountingFakeModel())
    document = _doc_with_lexical_noise(40)
    result = service.process(document, {"query": "authentication"})

    assert _semantic(result), "40 lexical matches starved the candidate budget"
    assert result.meta["semantic"].startswith("ok")


def test_lexical_findings_are_unaffected_by_the_wider_budget():
    service = _service_with(_CountingFakeModel())
    result = service.process(_doc_with_lexical_noise(15), {"query": "authentication"})

    lexical = [f for f in result.findings if f.details["match_type"] == "lexical"]
    assert len(lexical) == 15
    assert result.findings[0].details["match_type"] == "lexical_summary"
    assert result.findings[0].details["occurrences"] == 15


# === KS-2: embedding cache ===========================================


def test_repeated_query_reuses_the_document_embeddings():
    service = _service_with(_CountingFakeModel())
    document = _docx_doc(["Users supply credentials.", "The database is described."])

    service.process(document, {"query": "login"})
    service.process(document, {"query": "login"})
    service.process(document, {"query": "database"})

    assert service._model.passage_encode_calls == 1, "document was re-embedded"
    assert service._model.query_encode_calls == 3, "query must never be cached"


def test_different_documents_never_share_embeddings():
    """The cache must key on content, not on the service instance being
    reused across documents (app/cli.py walks folders with one instance)."""
    service = _service_with(_CountingFakeModel())
    first = _docx_doc(["Users supply credentials at sign-in."])
    second = _docx_doc(["The database stores element manager records."])

    service.process(first, {"query": "login"})
    service.process(second, {"query": "login"})

    assert service._model.passage_encode_calls == 2, "second document reused stale vectors"


def test_identical_paths_with_different_content_do_not_collide():
    """The dangerous case: same path, regenerated content. A path-keyed
    cache would serve the first document's embeddings for the second."""
    service = _service_with(_CountingFakeModel())
    original = _docx_doc(["Users supply credentials at sign-in."], path="report.docx")
    regenerated = _docx_doc(["The database stores records."], path="report.docx")

    service.process(original, {"query": "login"})
    result = service.process(regenerated, {"query": "login"})

    assert service._model.passage_encode_calls == 2
    for finding in _semantic(result):
        assert "credentials" not in finding.details["snippet"], (
            "snippet leaked from a different document with the same path"
        )


def test_cache_survives_a_query_that_finds_nothing():
    service = _service_with(_CountingFakeModel())
    document = _docx_doc(["Users supply credentials at sign-in."])

    service.process(document, {"query": "login"})
    service.process(document, {"query": "zzzznotpresent"})

    assert service._model.passage_encode_calls == 1


def test_chunk_boundaries_cannot_collide_in_the_cache_key():
    """['ab'] and ['a','b'] must hash differently, or two documents whose
    chunk text concatenates identically would share vectors."""
    service = _service_with(_CountingFakeModel())
    joined = _docx_doc(["credentials signin"])
    split = _docx_doc(["credentials", "signin"])

    service.process(joined, {"query": "login"})
    service.process(split, {"query": "login"})

    assert service._model.passage_encode_calls == 2


# === KS-3: relevance labelling (advisory, never filtering) ===========


def test_relevance_bands_are_ordered():
    band = service_module._relevance_band
    assert band(0.95) == "strong"
    assert band(service_module._RELEVANCE_STRONG) == "strong"
    assert band(0.50) == "moderate"
    assert band(service_module._RELEVANCE_MODERATE) == "moderate"
    assert band(0.30) == "weak"
    assert band(0.0) == "weak"


def test_semantic_finding_carries_a_relevance_band():
    chunk = service_module._Chunk(
        text="the sign-in flow", page=1, paragraph_index=0, chunk_index=0, char_start=0
    )
    finding = service_module._semantic_finding("keyword_search", "login", 0.32, chunk)
    assert finding.details["relevance"] == "weak"
    assert finding.details["score"] == pytest.approx(0.32)


def test_message_does_not_assert_a_relationship_it_cannot_prove():
    """A weak nearest-neighbour must not be phrased as established fact —
    the project rule is 'never invent evidence'."""
    chunk = service_module._Chunk(
        text="unrelated text", page=1, paragraph_index=0, chunk_index=0, char_start=0
    )
    message = service_module._semantic_finding("keyword_search", "orchids", 0.31, chunk).message
    assert "Passage related to" not in message
    assert "weak" in message


def test_relevance_band_never_filters_results():
    """Labelling must not become a hidden threshold."""
    service = _service_with(_CountingFakeModel())
    document = _docx_doc(["The database stores element manager records."])
    result = service.process(document, {"query": "login"})

    semantic = _semantic(result)
    assert semantic, "a weak match must still be returned, only labelled"
    assert semantic[0].details["relevance"] == "weak"


def test_threshold_remains_disabled_unless_explicitly_configured():
    assert service_module._SEMANTIC_THRESHOLD is None, (
        "an uncalibrated floor must never be enabled by default"
    )


def test_threshold_filters_only_when_set(monkeypatch):
    """The opt-in mechanism works, for whoever calibrates it later."""
    monkeypatch.setattr(service_module, "_SEMANTIC_THRESHOLD", 0.90)
    pattern = service_module._query_pattern("login")
    chunk = service_module._Chunk(
        text="unrelated", page=1, paragraph_index=0, chunk_index=0, char_start=0
    )
    assert service_module._select_semantic([(0.30, chunk)], pattern, 5) == []
    assert len(service_module._select_semantic([(0.95, chunk)], pattern, 5)) == 1


def test_report_columns_still_cover_every_details_key():
    service = KeywordSearchService()
    columns = set(service.report_columns())
    chunk = service_module._Chunk(
        text="t", page=1, paragraph_index=0, chunk_index=0, char_start=0
    )
    finding = service_module._semantic_finding("keyword_search", "q", 0.5, chunk)
    assert set(finding.details) <= columns


# === KS-5: batch size is a named constant, not a literal =============


def test_encode_batch_size_is_configurable_and_sane():
    assert isinstance(service_module._ENCODE_BATCH_SIZE, int)
    assert service_module._ENCODE_BATCH_SIZE >= 1


# === KS-4: MCP truncation must not starve semantic findings ==========

mcp_server = pytest.importorskip(
    "app.mcp_server", reason="mcp not installed"
)


def _finding(match_type: str, index: int) -> Finding:
    return Finding(
        feature="keyword_search",
        severity="info",
        page=1,
        message=f"{match_type} {index}",
        confidence=None,
        details={"match_type": match_type, "snippet": f"{match_type}-{index}"},
    )


def test_semantic_findings_survive_mcp_truncation():
    limit = mcp_server.MAX_FINDINGS
    findings = [_finding("lexical", i) for i in range(limit + 50)]
    findings += [_finding("semantic", i) for i in range(5)]

    kept = mcp_server._keep(findings, limit)

    assert len(kept) == limit
    assert sum(1 for f in kept if f.details["match_type"] == "semantic") == 5


def test_truncation_reports_the_true_total():
    limit = mcp_server.MAX_FINDINGS
    from common.contracts import FeatureResult

    findings = [_finding("lexical", i) for i in range(limit + 20)]
    findings += [_finding("semantic", i) for i in range(3)]
    payload = mcp_server._payload(
        FeatureResult(feature="keyword_search", status="ok", findings=findings)
    )

    assert payload["truncated"] is True
    assert payload["finding_count"] == len(findings)
    assert sum(1 for f in payload["findings"] if f["match_type"] == "semantic") == 3


def test_short_result_is_returned_unchanged():
    findings = [_finding("lexical", i) for i in range(3)]
    assert mcp_server._keep(findings, mcp_server.MAX_FINDINGS) == findings


def test_keep_never_exceeds_the_limit_even_if_semantic_dominates():
    """The reservation in _keep() only stays within budget while the scarce
    class is small. _SEMANTIC_TOP_K (5) enforces that today, but nothing
    couples the two constants, so the cap is clamped defensively."""
    limit = mcp_server.MAX_FINDINGS
    findings = [_finding("lexical", i) for i in range(300)]
    findings += [_finding("semantic", i) for i in range(limit + 50)]

    kept = mcp_server._keep(findings, limit)

    assert len(kept) == limit


@pytest.mark.parametrize("n_semantic", [0, 1, 5, 50, 99, 100, 150, 400])
def test_keep_respects_the_limit_at_every_semantic_ratio(n_semantic):
    limit = mcp_server.MAX_FINDINGS
    findings = [_finding("lexical", i) for i in range(300)]
    findings += [_finding("semantic", i) for i in range(n_semantic)]

    assert len(mcp_server._keep(findings, limit)) == limit


def test_clamp_does_not_change_behaviour_at_realistic_ratios():
    """Regression guard: the defensive clamp must be a no-op for the volumes
    the service actually produces (semantic capped at _SEMANTIC_TOP_K)."""
    limit = mcp_server.MAX_FINDINGS
    top_k = service_module._SEMANTIC_TOP_K
    findings = [_finding("lexical", i) for i in range(300)]
    findings += [_finding("semantic", i) for i in range(top_k)]

    kept = mcp_server._keep(findings, limit)

    assert len(kept) == limit
    assert sum(1 for f in kept if f.details["match_type"] == "semantic") == top_k
    assert sum(1 for f in kept if f.details["match_type"] == "lexical") == limit - top_k


def test_features_without_match_type_keep_the_plain_head_slice():
    """broken_links and spell_check have no scarce class; behaviour for them
    must be identical to the original findings[:limit]."""
    plain = [
        Finding(feature="broken_links", severity="warning", page=1,
                message=f"m{i}", confidence=None, details={"reason": "x"})
        for i in range(mcp_server.MAX_FINDINGS + 10)
    ]
    kept = mcp_server._keep(plain, mcp_server.MAX_FINDINGS)
    assert kept == plain[: mcp_server.MAX_FINDINGS]
