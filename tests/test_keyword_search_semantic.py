"""Phase 2 tests for semantic keyword search (BGE + FAISS).

Three tiers, so meaningful coverage exists whatever is installed:

  1. Dependency-free — chunking, deduplication, ordering, schema and the
     model-loading fallbacks. These exercise pure functions and need
     neither numpy, faiss nor sentence-transformers.
  2. Fake-encoder — the full FAISS path driven by a stub model, so
     ranking and provenance are tested without the real weights. Needs
     numpy + faiss only.
  3. Real-model — skipped unless sentence-transformers *and* locally
     provisioned weights are present. Covers the acceptance criterion
     that "login" retrieves a paragraph about authentication.

Additive: tests/test_contract.py and tests/test_keyword_search.py are not
modified by this file.
"""
from __future__ import annotations

import importlib
import importlib.util
import os

import pytest

from common.contracts import Document, Page, Paragraph

service_module = importlib.import_module("features.keyword_search.service")
KeywordSearchService = getattr(service_module, "KeywordSearchService", None)

pytestmark = pytest.mark.skipif(
    KeywordSearchService is None, reason="keyword_search not implemented yet"
)

_chunks = service_module._chunks
_select_semantic = service_module._select_semantic
_semantic_finding = service_module._semantic_finding
_query_pattern = service_module._query_pattern
_Chunk = service_module._Chunk


def _service():
    return KeywordSearchService()


def _pdf_doc(page_texts: list[str]) -> Document:
    return Document(
        path="doc.pdf",
        format="pdf",
        page_count=len(page_texts),
        pages=[Page(number=i, text=t) for i, t in enumerate(page_texts, start=1)],
    )


def _docx_doc(paragraph_texts: list[str]) -> Document:
    return Document(
        path="doc.docx",
        format="docx",
        page_count=1,
        pages=[Page(number=1, text="\n".join(paragraph_texts))],
        paragraphs=[
            Paragraph(text=t, page=1, index=i) for i, t in enumerate(paragraph_texts)
        ],
    )


def _chunk(text="passage", page=1, paragraph_index=0, chunk_index=0, char_start=0):
    return _Chunk(
        text=text,
        page=page,
        paragraph_index=paragraph_index,
        chunk_index=chunk_index,
        char_start=char_start,
    )


# === tier 1: dependency-free ==========================================
# --- chunking ---------------------------------------------------------


def test_chunks_carry_page_and_paragraph_provenance():
    document = _docx_doc(["Alpha text here.", "Beta text here.", "Gamma text here."])
    chunks = _chunks(document)
    assert [c.page for c in chunks] == [1, 1, 1]
    assert [c.paragraph_index for c in chunks] == [0, 1, 2]


def test_chunk_index_is_sequential_and_unique():
    document = _pdf_doc(["One. Two. Three.", "Four. Five."])
    chunks = _chunks(document)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_chunk_text_is_a_verbatim_substring_of_its_unit():
    document = _docx_doc(["The OSS authentication workflow is described here."])
    chunk = _chunks(document)[0]
    assert chunk.text in document.paragraphs[0].text


def test_char_start_locates_the_chunk_within_its_unit():
    document = _docx_doc(["First sentence. Second sentence. Third sentence."])
    source = document.paragraphs[0].text
    for chunk in _chunks(document):
        assert source[chunk.char_start : chunk.char_start + len(chunk.text)] == chunk.text


def test_long_unit_is_split_into_multiple_chunks():
    long_text = " ".join(f"Sentence number {i} about authentication." for i in range(60))
    document = _pdf_doc([long_text])
    chunks = _chunks(document)
    assert len(chunks) > 1


def test_a_unit_without_sentence_punctuation_is_still_split():
    """A PDF page with no full stops must not become one giant chunk that
    the model would silently truncate."""
    document = _pdf_doc(["word " * 500])
    chunks = _chunks(document)
    assert len(chunks) > 1
    assert all(len(c.text) <= service_module._CHUNK_MAX_CHARS + 1 for c in chunks)


def test_empty_document_produces_no_chunks():
    assert _chunks(Document(path="e.pdf", format="pdf", page_count=0)) == []


def test_chunks_prefer_paragraphs_over_pages():
    """Same no-double-counting rule as the lexical pass."""
    text = "Only one sentence here."
    document = Document(
        path="d.pdf",
        format="pdf",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    chunks = _chunks(document)
    assert len(chunks) == 1
    assert chunks[0].paragraph_index == 0


# --- selection: dedupe, cap, ordering ---------------------------------


def test_selection_drops_chunks_containing_an_exact_lexical_match():
    pattern = _query_pattern("authentication")
    candidates = [
        (0.9, _chunk(text="the authentication step", chunk_index=0)),
        (0.8, _chunk(text="the login step", chunk_index=1)),
    ]
    selected = _select_semantic(candidates, pattern, 5)
    assert [c.chunk_index for _s, c in selected] == [1]


def test_selection_caps_at_the_limit():
    pattern = _query_pattern("login")
    candidates = [
        (0.9 - i / 100, _chunk(text=f"passage {i}", chunk_index=i)) for i in range(10)
    ]
    assert len(_select_semantic(candidates, pattern, 5)) == 5


def test_selection_may_return_fewer_than_the_limit():
    pattern = _query_pattern("login")
    candidates = [(0.7, _chunk(text="one passage", chunk_index=0))]
    assert len(_select_semantic(candidates, pattern, 5)) == 1


def test_selection_returns_empty_when_everything_is_deduped():
    pattern = _query_pattern("login")
    candidates = [(0.9, _chunk(text="a login form", chunk_index=i)) for i in range(3)]
    assert _select_semantic(candidates, pattern, 5) == []


def test_selection_orders_by_score_descending():
    pattern = _query_pattern("login")
    candidates = [
        (0.5, _chunk(text="low", chunk_index=0)),
        (0.9, _chunk(text="high", chunk_index=1)),
        (0.7, _chunk(text="mid", chunk_index=2)),
    ]
    assert [s for s, _c in _select_semantic(candidates, pattern, 5)] == [0.9, 0.7, 0.5]


def test_selection_tie_break_is_page_then_chunk_index():
    pattern = _query_pattern("login")
    candidates = [
        (0.8, _chunk(text="d", page=2, chunk_index=9)),
        (0.8, _chunk(text="c", page=1, chunk_index=7)),
        (0.8, _chunk(text="b", page=1, chunk_index=3)),
    ]
    selected = _select_semantic(candidates, pattern, 5)
    assert [(c.page, c.chunk_index) for _s, c in selected] == [(1, 3), (1, 7), (2, 9)]


def test_threshold_is_disabled_and_does_not_filter():
    assert service_module._SEMANTIC_THRESHOLD is None
    pattern = _query_pattern("login")
    candidates = [(0.01, _chunk(text="barely related", chunk_index=0))]
    assert len(_select_semantic(candidates, pattern, 5)) == 1


# --- semantic finding schema ------------------------------------------


def test_semantic_finding_records_score_in_confidence_and_details():
    finding = _semantic_finding("keyword_search", "login", 0.7321, _chunk())
    assert finding.confidence == pytest.approx(0.7321)
    assert finding.details["score"] == pytest.approx(0.7321)


def test_semantic_finding_schema_and_provenance():
    chunk = _chunk(text="the sign-in flow", page=4, paragraph_index=2, chunk_index=6)
    finding = _semantic_finding("keyword_search", "login", 0.8, chunk)
    assert finding.details["match_type"] == "semantic"
    assert finding.details["occurrences"] == 0
    assert finding.details["pages"] == [4]
    assert finding.details["paragraph_index"] == 2
    assert finding.details["chunk_index"] == 6
    assert finding.page == 4
    assert finding.details["snippet"] == "the sign-in flow"


def test_report_columns_cover_semantic_details_keys():
    finding = _semantic_finding("keyword_search", "login", 0.5, _chunk())
    assert set(finding.details) <= set(_service().report_columns())


# --- model loading and graceful fallback ------------------------------


def test_is_available_stays_true_without_semantic_dependencies():
    assert _service().is_available() is True


def test_model_path_honours_the_environment_variable(monkeypatch):
    monkeypatch.setenv("DCCAT_BGE_MODEL_PATH", os.path.join("some", "where"))
    assert service_module._model_path() == os.path.join("some", "where")


def test_model_path_defaults_to_the_local_models_directory(monkeypatch):
    monkeypatch.delenv("DCCAT_BGE_MODEL_PATH", raising=False)
    path = service_module._model_path()
    assert path.endswith(os.path.join("models", "bge-base-en-v1.5"))
    assert os.path.isabs(path)


def test_missing_model_returns_none_and_is_not_retried(monkeypatch):
    monkeypatch.setenv("DCCAT_BGE_MODEL_PATH", os.path.join("no", "such", "dir"))
    service = _service()

    assert service._ensure_model() is None
    assert service._model_load_attempted is True
    assert service._model_error

    # A second call must not re-attempt the load: app/cli.py reuses one
    # instance across every document in a folder walk.
    service._model_error = "SENTINEL"
    assert service._ensure_model() is None
    assert service._model_error == "SENTINEL"


def test_unavailable_semantic_still_returns_ok_with_a_reason(monkeypatch):
    monkeypatch.setenv("DCCAT_BGE_MODEL_PATH", os.path.join("no", "such", "dir"))
    document = _pdf_doc(["Authentication failed. Retry authentication."])
    result = _service().process(document, {"query": "authentication"})
    assert result.status == "ok"
    assert result.meta["semantic"].startswith("unavailable")


def test_lexical_output_is_unchanged_when_semantic_is_unavailable(monkeypatch):
    monkeypatch.setenv("DCCAT_BGE_MODEL_PATH", os.path.join("no", "such", "dir"))
    document = _pdf_doc(["Authentication failed. Retry authentication."])
    result = _service().process(document, {"query": "authentication"})
    assert result.findings[0].details["match_type"] == "lexical_summary"
    assert result.findings[0].details["occurrences"] == 2
    assert all(f.details["match_type"] != "semantic" for f in result.findings)


# === tier 2: fake encoder (needs numpy + faiss) =======================


class _FakeModel:
    """Stand-in for SentenceTransformer with deterministic vectors.

    Each text is scored on how many keywords it shares with a fixed
    vocabulary, so ranking is fully controlled by the test. Emits vectors
    of the real embedding width so the service's dimension guard passes.
    """

    VOCAB = ("authentication", "login", "credentials", "database")

    def encode(
        self,
        texts,
        normalize_embeddings=False,
        convert_to_numpy=True,
        batch_size=None,
    ):
        import numpy as np

        dim = service_module._EMBEDDING_DIM
        vectors = []
        for text in texts:
            lowered = text.lower()
            vector = [0.0] * dim
            for position, word in enumerate(self.VOCAB):
                if word in lowered:
                    vector[position] = 1.0
            if not any(vector):
                vector[len(self.VOCAB)] = 1.0  # unrelated-but-nonzero direction
            vectors.append(vector)
        array = np.array(vectors, dtype="float32")
        if normalize_embeddings:
            norms = np.linalg.norm(array, axis=1, keepdims=True)
            array = array / np.maximum(norms, 1e-12)
        return array


def _with_fake_model():
    pytest.importorskip("numpy")
    pytest.importorskip("faiss")
    service = _service()
    service._model = _FakeModel()
    service._model_load_attempted = True
    return service


def test_fake_encoder_finds_a_related_passage_without_the_query_word():
    service = _with_fake_model()
    document = _docx_doc(
        [
            "The topology diagram shows the antenna layout.",
            "Users provide credentials during authentication.",
        ]
    )
    result = service.process(document, {"query": "login credentials"})
    assert result.status == "ok"
    semantic = [f for f in result.findings if f.details["match_type"] == "semantic"]
    assert semantic
    assert semantic[0].details["paragraph_index"] == 1
    assert semantic[0].confidence is not None


def test_fake_encoder_semantic_results_are_capped_at_five():
    service = _with_fake_model()
    document = _docx_doc([f"Passage {i} about credentials." for i in range(12)])
    result = service.process(document, {"query": "login"})
    semantic = [f for f in result.findings if f.details["match_type"] == "semantic"]
    assert len(semantic) <= 5


def test_fake_encoder_keeps_lexical_aggregate_first():
    service = _with_fake_model()
    document = _docx_doc(
        ["Authentication is required.", "Users supply credentials at sign-in."]
    )
    result = service.process(document, {"query": "authentication"})
    assert result.findings[0].details["match_type"] == "lexical_summary"


def test_fake_encoder_never_returns_a_chunk_holding_an_exact_match():
    service = _with_fake_model()
    document = _docx_doc(
        ["Authentication is required here.", "Users supply credentials at sign-in."]
    )
    result = service.process(document, {"query": "authentication"})
    pattern = _query_pattern("authentication")
    for finding in result.findings:
        if finding.details["match_type"] == "semantic":
            assert not pattern.search(finding.details["snippet"])


def test_fake_encoder_records_ok_note_in_meta():
    service = _with_fake_model()
    document = _docx_doc(["Users supply credentials at sign-in."])
    result = service.process(document, {"query": "login"})
    assert result.meta["semantic"].startswith("ok")


def test_fake_encoder_handles_a_single_chunk_document():
    """k is clamped to index.ntotal, so a tiny document must not produce
    findings from FAISS's -1 padding."""
    service = _with_fake_model()
    document = _docx_doc(["Users supply credentials."])
    result = service.process(document, {"query": "login"})
    assert result.status == "ok"
    semantic = [f for f in result.findings if f.details["match_type"] == "semantic"]
    assert len(semantic) <= 1


def test_fake_encoder_semantic_snippets_are_verbatim_document_text():
    service = _with_fake_model()
    document = _docx_doc(["Users supply credentials during the sign-in step."])
    result = service.process(document, {"query": "login"})
    source = " ".join(document.paragraphs[0].text.split())
    for finding in result.findings:
        if finding.details["match_type"] == "semantic":
            assert finding.details["snippet"] in source


# === tier 3: real model (skipped unless provisioned) ==================


def _real_model_available() -> bool:
    if importlib.util.find_spec("sentence_transformers") is None:
        return False
    if importlib.util.find_spec("faiss") is None:
        return False
    return os.path.isdir(service_module._model_path())


real_model = pytest.mark.skipif(
    not _real_model_available(),
    reason="sentence-transformers and local BGE weights are not provisioned",
)


@real_model
def test_real_model_login_retrieves_an_authentication_passage():
    """Acceptance criterion: a query with no lexical match still finds the
    semantically related paragraph."""
    service = _service()
    document = _docx_doc(
        [
            "The topology diagram shows the antenna layout for the site.",
            "Users must present valid authentication tokens before access.",
            "Cable lengths are listed in the appendix.",
        ]
    )
    result = service.process(document, {"query": "login"})
    assert result.status == "ok"
    semantic = [f for f in result.findings if f.details["match_type"] == "semantic"]
    assert semantic
    assert semantic[0].details["paragraph_index"] == 1


@real_model
def test_real_model_loads_only_once_per_instance():
    service = _service()
    document = _docx_doc(["Users must authenticate before access."])
    service.process(document, {"query": "login"})
    first = service._model
    service.process(document, {"query": "password"})
    assert service._model is first    