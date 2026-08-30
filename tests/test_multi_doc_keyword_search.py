"""Tests for the multi_doc_keyword_search feature.

Additive: tests/test_contract.py and the three tests/test_keyword_search*.py
files are not touched by this one. Nothing here imports
features/keyword_search/ — the two features are independent, and a test
that coupled them would defeat the point.

Uses the same load-and-skip pattern as the rest of the suite so the file
stays collectible if the feature is ever removed.
"""
from __future__ import annotations

import importlib
import os

import pytest

from common.contracts import Document, Page, Paragraph


def _load(module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError):
        return None


MultiDocKeywordSearchService = _load(
    "features.multi_doc_keyword_search.service", "MultiDocKeywordSearchService"
)

pytestmark = pytest.mark.skipif(
    MultiDocKeywordSearchService is None,
    reason="multi_doc_keyword_search not implemented yet",
)


def _service():
    return MultiDocKeywordSearchService()


def _pdf_doc(page_texts: list[str], path: str = "doc.pdf") -> Document:
    """A PDF-shaped document: pages only, no paragraphs."""
    return Document(
        path=path,
        format="pdf",
        page_count=len(page_texts),
        pages=[Page(number=i, text=t) for i, t in enumerate(page_texts, start=1)],
    )


def _docx_doc(paragraph_texts: list[str], path: str = "doc.docx") -> Document:
    """A DOCX-shaped document: everything on page 1, real paragraphs."""
    return Document(
        path=path,
        format="docx",
        page_count=1,
        pages=[Page(number=1, text="\n".join(paragraph_texts))],
        paragraphs=[
            Paragraph(text=t, page=1, index=i) for i, t in enumerate(paragraph_texts)
        ],
    )


def _by_document(result) -> dict[str, int]:
    return {doc.path: doc.match_count for doc in result.documents}


# --- Test 1: single document, multiple matches -------------------------


def test_single_document_returns_every_occurrence():
    document = _pdf_doc(
        [
            "Authentication is required. Retry authentication after refresh.",
            "The AUTHENTICATION token expires hourly.",
        ]
    )
    result = _service().search_documents([document], "authentication")

    assert result.status == "ok"
    assert result.total_matches == 3
    assert result.documents_searched == 1
    assert result.documents_with_matches == 1
    # One finding per occurrence, not one aggregate per unit.
    assert len(result.findings()) == 3


def test_occurrence_index_is_sequential_within_a_document():
    document = _pdf_doc(["authentication authentication", "authentication"])
    result = _service().search_documents([document], "authentication")

    indexes = [f.details["occurrence_index"] for f in result.findings()]
    assert indexes == [1, 2, 3]


# --- Test 2: multiple documents ----------------------------------------


def test_aggregates_across_multiple_documents():
    doc_a = _pdf_doc(
        [
            "Authentication overview.",
            "Configure authentication here.",
            "Authentication failures are logged.",
        ],
        path="a.pdf",
    )
    doc_b = _pdf_doc(
        ["The authentication token.", "Authentication retries."], path="b.pdf"
    )
    doc_c = _pdf_doc(["Nothing relevant on this page.", "Still nothing."], path="c.pdf")

    result = _service().search_documents([doc_a, doc_b, doc_c], "authentication")

    assert result.status == "ok"
    assert result.total_matches == 5
    assert result.documents_searched == 3
    assert result.documents_with_matches == 2
    assert _by_document(result) == {"a.pdf": 3, "b.pdf": 2, "c.pdf": 0}


def test_search_does_not_stop_at_the_first_matching_document():
    docs = [_pdf_doc([f"authentication in doc {i}"], path=f"d{i}.pdf") for i in range(4)]
    result = _service().search_documents(docs, "authentication")

    assert _by_document(result) == {f"d{i}.pdf": 1 for i in range(4)}


def test_every_finding_names_its_source_document():
    doc_a = _pdf_doc(["authentication"], path="a.pdf")
    doc_b = _pdf_doc(["authentication"], path="b.pdf")
    result = _service().search_documents([doc_a, doc_b], "authentication")

    assert {f.details["document"] for f in result.findings()} == {"a.pdf", "b.pdf"}


# --- Test 3: keyword absent everywhere ---------------------------------


def test_no_matches_anywhere_is_a_clean_ok_result():
    docs = [
        _pdf_doc(["Configuration overview."], path="a.pdf"),
        _pdf_doc(["Topology diagram."], path="b.pdf"),
    ]
    result = _service().search_documents(docs, "authentication")

    assert result.status == "ok"  # not an error
    assert result.error is None
    assert result.total_matches == 0
    assert result.documents_with_matches == 0
    assert result.documents_searched == 2
    assert result.findings() == []


def test_no_documents_at_all_is_a_clean_ok_result():
    result = _service().search_documents([], "authentication")

    assert result.status == "ok"
    assert result.documents_searched == 0
    assert result.total_matches == 0


# --- Test 4: case-insensitivity ----------------------------------------


@pytest.mark.parametrize(
    "written", ["authentication", "Authentication", "AUTHENTICATION", "AuThEnTiCaTiOn"]
)
def test_matching_is_case_insensitive(written):
    document = _pdf_doc([f"The {written} step."])
    result = _service().search_documents([document], "authentication")

    assert result.total_matches == 1


def test_keyword_casing_does_not_change_the_result():
    document = _pdf_doc(["Authentication and authentication."])
    lower = _service().search_documents([document], "authentication").total_matches
    upper = _service().search_documents([document], "AUTHENTICATION").total_matches

    assert lower == upper == 2


def test_match_text_preserves_the_casing_found_in_the_document():
    document = _pdf_doc(["AUTHENTICATION is required."])
    result = _service().search_documents([document], "authentication")

    assert result.findings()[0].details["match_text"] == "AUTHENTICATION"


# --- Test 5: whole-word behaviour --------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "preauthentication is different",
        "authentications are plural",
        "reauthentications everywhere",
        "deauthenticationlog",
    ],
)
def test_substrings_of_larger_words_are_not_matched(text):
    result = _service().search_documents([_pdf_doc([text])], "authentication")

    assert result.total_matches == 0


def test_punctuation_adjacent_matches_are_still_whole_words():
    document = _pdf_doc(["(authentication), authentication. authentication!"])
    result = _service().search_documents([document], "authentication")

    assert result.total_matches == 3


def test_keyword_with_non_word_edges_still_matches():
    # A \b-based pattern would never match a keyword ending in a digit-free
    # symbol; the lookaround form does.
    document = _pdf_doc(["The code ERR#01 was logged."])
    result = _service().search_documents([document], "ERR#01")

    assert result.total_matches == 1


def test_multi_word_keyword_matches_across_a_line_break():
    document = _pdf_doc(["the configuration\nworkflow used here"])
    result = _service().search_documents([document], "configuration workflow")

    assert result.total_matches == 1


# --- Test 6: empty keyword ---------------------------------------------


@pytest.mark.parametrize("keyword", ["", "   ", "\n\t", None])
def test_empty_keyword_is_a_validation_error(keyword):
    docs = [_pdf_doc(["authentication everywhere"])]
    result = _service().search_documents(docs, keyword)

    assert result.status == "failed"
    assert result.error
    assert result.total_matches == 0
    assert result.findings() == []


def test_empty_keyword_fails_the_path_based_search_too(tmp_path):
    result = _service().search(str(tmp_path), "")

    assert result.status == "failed"
    assert result.error


def test_wrongly_typed_keyword_fails_loudly_rather_than_matching_nothing():
    result = _service().search_documents([_pdf_doc(["authentication"])], 42)

    assert result.status == "failed"
    assert "string" in result.error


def test_process_rejects_a_missing_keyword():
    result = _service().process(_pdf_doc(["authentication"]), {})

    assert result.status == "failed"
    assert result.error


# --- Test 7: page information ------------------------------------------


def test_page_numbers_are_reported_per_match():
    document = _pdf_doc(
        [
            "nothing here",
            "authentication on the second page",
            "nothing again",
            "authentication on the fourth page",
        ]
    )
    result = _service().search_documents([document], "authentication")

    assert [f.page for f in result.findings()] == [2, 4]
    assert [f.details["page"] for f in result.findings()] == [2, 4]


def test_docx_matches_carry_paragraph_locality():
    document = _docx_doc(
        ["Intro paragraph.", "Authentication is required.", "Closing paragraph."]
    )
    result = _service().search_documents([document], "authentication")

    finding = result.findings()[0]
    assert finding.page == 1  # DOCX puts everything on page 1
    assert finding.details["paragraph_index"] == 1


def test_paragraphs_and_pages_are_never_both_counted():
    # The parser derives paragraphs from page text; counting both would
    # report every match twice.
    text = "Authentication is required."
    document = Document(
        path="both.docx",
        format="docx",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    result = _service().search_documents([document], "authentication")

    assert result.total_matches == 1


# --- Test 8: context ---------------------------------------------------


def test_context_contains_the_surrounding_sentence():
    document = _pdf_doc(
        ["User authentication is required before accessing the system."]
    )
    result = _service().search_documents([document], "authentication")

    context = result.findings()[0].details["context"]
    assert "User authentication is required" in context
    assert "accessing the system" in context


def test_context_is_verbatim_document_text_and_is_ellipsed_when_cut():
    filler = "word " * 60
    document = _pdf_doc([filler + "authentication " + filler])
    result = _service().search_documents([document], "authentication")

    context = result.findings()[0].details["context"]
    assert context.startswith("...")
    assert context.endswith("...")
    assert "authentication" in context
    # Whitespace-collapsed verbatim text, nothing generated.
    assert set(context.strip(".").split()) <= {"word", "authentication"}


def test_each_occurrence_gets_its_own_context():
    document = _pdf_doc(
        ["First authentication mention here. Second authentication mention there."]
    )
    result = _service().search_documents([document], "authentication")

    contexts = [f.details["context"] for f in result.findings()]
    assert len(contexts) == 2
    assert "First" in contexts[0]
    assert "there" in contexts[1]


# --- discovery and per-document error isolation ------------------------


def test_discovers_documents_in_a_folder(tmp_path):
    pytest.importorskip("pymupdf")
    import pymupdf as fitz

    for name in ("a.pdf", "b.pdf"):
        doc = fitz.open()
        page = doc.new_page()
        page.insert_text((72, 72), "Authentication is required.", fontsize=12)
        doc.save(str(tmp_path / name))
        doc.close()
    (tmp_path / "notes.txt").write_text("authentication", encoding="utf-8")

    result = _service().search(str(tmp_path), "authentication")

    assert result.status == "ok"
    assert result.documents_searched == 2  # the .txt is not an eligible document
    assert result.total_matches == 2


def test_a_missing_path_is_reported_without_failing_the_search(tmp_path):
    pytest.importorskip("pymupdf")
    import pymupdf as fitz

    good = tmp_path / "good.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Authentication is required.", fontsize=12)
    doc.save(str(good))
    doc.close()

    missing = str(tmp_path / "nope.pdf")
    result = _service().search([str(good), missing], "authentication")

    assert result.status == "ok"
    assert result.total_matches == 1  # the readable document still reported
    assert any(problem["document"] == missing for problem in result.errors)


def test_an_unreadable_document_does_not_stop_the_others(tmp_path):
    pytest.importorskip("pymupdf")
    import pymupdf as fitz

    good = tmp_path / "good.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Authentication is required.", fontsize=12)
    doc.save(str(good))
    doc.close()

    broken = tmp_path / "broken.pdf"
    broken.write_bytes(b"this is not a pdf")

    result = _service().search(str(tmp_path), "authentication")

    assert result.status == "ok"
    assert result.total_matches == 1
    assert [p["document"] for p in result.errors] == [os.path.normpath(str(broken))]


def test_the_same_document_reached_twice_is_searched_once(tmp_path):
    pytest.importorskip("pymupdf")
    import pymupdf as fitz

    path = tmp_path / "a.pdf"
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Authentication is required.", fontsize=12)
    doc.save(str(path))
    doc.close()

    result = _service().search([str(path), str(tmp_path)], "authentication")

    assert result.documents_searched == 1
    assert result.total_matches == 1


# --- contract compliance and payload shape -----------------------------


def test_process_is_contract_compliant_on_an_empty_document():
    result = _service().process(
        Document(path="empty.pdf", format="pdf", page_count=0), {"keyword": "x"}
    )

    assert result.status in {"ok", "failed", "skipped"}
    assert result.feature == "multi_doc_keyword_search"
    assert result.findings == []


def test_process_never_raises_with_options_none():
    result = _service().process(_pdf_doc(["authentication"]), None)

    assert result.status in {"ok", "failed", "skipped"}


def test_process_returns_one_finding_per_occurrence():
    result = _service().process(
        _pdf_doc(["authentication and authentication"]), {"keyword": "authentication"}
    )

    assert result.status == "ok"
    assert len(result.findings) == 2
    assert result.meta["total_matches"] == 2


def test_report_columns_cover_every_detail_key():
    service = _service()
    result = service.search_documents([_pdf_doc(["authentication"])], "authentication")

    base_columns = {"page", "severity", "message", "confidence"}
    covered = set(service.report_columns()) | base_columns
    for finding in result.findings():
        assert set(finding.details) <= covered


def test_to_dict_payload_shape():
    doc_a = _pdf_doc(["authentication", "authentication"], path="a.pdf")
    doc_b = _pdf_doc(["nothing"], path="b.pdf")
    payload = _service().search_documents([doc_a, doc_b], "authentication").to_dict()

    assert payload["status"] == "ok"
    assert payload["keyword"] == "authentication"
    assert payload["documents_searched"] == 2
    assert payload["documents_with_matches"] == 1
    assert payload["total_matches"] == 2
    assert [d["document"] for d in payload["documents"]] == ["a.pdf", "b.pdf"]
    first = payload["documents"][0]["matches"][0]
    assert set(first) == {
        "page",
        "keyword",
        "match_text",
        "context",
        "paragraph_index",
        "occurrence_index",
    }


def test_to_dict_truncates_per_document_but_keeps_counts_honest():
    document = _pdf_doc(["authentication " * 10])
    payload = (
        _service()
        .search_documents([document], "authentication")
        .to_dict(limit_per_document=3)
    )

    doc_payload = payload["documents"][0]
    assert payload["total_matches"] == 10  # count reflects the whole result
    assert doc_payload["match_count"] == 10
    assert len(doc_payload["matches"]) == 3
    assert doc_payload["truncated"] is True


def test_to_feature_result_carries_every_finding_and_the_aggregates():
    doc_a = _pdf_doc(["authentication", "authentication"], path="a.pdf")
    doc_b = _pdf_doc(["authentication"], path="b.pdf")
    feature_result = (
        _service().search_documents([doc_a, doc_b], "authentication").to_feature_result()
    )

    assert feature_result.feature == "multi_doc_keyword_search"
    assert feature_result.status == "ok"
    assert len(feature_result.findings) == 3
    assert feature_result.meta["documents_with_matches"] == 2
    assert feature_result.meta["total_matches"] == 3


# --- the search is literal, never semantic -----------------------------


@pytest.mark.parametrize(
    "related", ["login", "authorization", "verification", "identity", "credentials"]
)
def test_related_terms_are_never_matched(related):
    document = _pdf_doc([f"The {related} step is documented here."])
    result = _service().search_documents([document], "authentication")

    assert result.total_matches == 0


def test_feature_imports_nothing_from_the_existing_keyword_search():
    import features.multi_doc_keyword_search.discovery as discovery
    import features.multi_doc_keyword_search.matcher as matcher
    import features.multi_doc_keyword_search.service as service

    for module in (service, matcher, discovery):
        source = open(module.__file__, encoding="utf-8").read()
        assert "features.keyword_search" not in source
        assert "from features.keyword_search" not in source
