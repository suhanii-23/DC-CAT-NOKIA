"""Phase 1 tests for the lexical keyword_search feature.

Additive: tests/test_contract.py owns the cross-feature contract checks
and is not touched by this file. These cover behaviour specific to the
lexical implementation — phrase matching, per-unit snippets, paragraph
locality, and malformed input.

Uses the same load-and-skip pattern as tests/test_contract.py so the
suite stays collectible if this feature is ever emptied out again.
"""
from __future__ import annotations

import importlib

import pytest

from common.contracts import Document, Page, Paragraph


def _load(module_path: str, class_name: str):
    try:
        module = importlib.import_module(module_path)
        return getattr(module, class_name)
    except (ImportError, AttributeError):
        return None


KeywordSearchService = _load("features.keyword_search.service", "KeywordSearchService")

pytestmark = pytest.mark.skipif(
    KeywordSearchService is None, reason="keyword_search not implemented yet"
)


def _service():
    return KeywordSearchService()


def _pdf_doc(page_texts: list[str]) -> Document:
    """A PDF-shaped document: pages only, no paragraphs."""
    return Document(
        path="doc.pdf",
        format="pdf",
        page_count=len(page_texts),
        pages=[Page(number=i, text=t) for i, t in enumerate(page_texts, start=1)],
    )


def _docx_doc(paragraph_texts: list[str]) -> Document:
    """A DOCX-shaped document: everything on page 1, real paragraphs."""
    return Document(
        path="doc.docx",
        format="docx",
        page_count=1,
        pages=[Page(number=1, text="\n".join(paragraph_texts))],
        paragraphs=[
            Paragraph(text=t, page=1, index=i) for i, t in enumerate(paragraph_texts)
        ],
    )


def _summary(result):
    return result.findings[0].details


def _unit_findings(result):
    # Lexical per-unit findings only. This used to be `result.findings[1:]`,
    # but Phase 2 appends semantic findings after the lexical ones, so
    # slicing would pull those in too.
    return [f for f in result.findings if f.details["match_type"] == "lexical"]


def _lexical_findings(result):
    """Every lexical finding — the aggregate summary and the per-unit ones."""
    return [
        f for f in result.findings if f.details["match_type"].startswith("lexical")
    ]


# --- phrase matching ---------------------------------------------------


def test_phrase_matches_across_a_line_break():
    document = _pdf_doc(["This describes the OSS authentication and configuration\nworkflow."])
    result = _service().process(document, {"query": "configuration workflow"})
    assert result.status == "ok"
    assert _summary(result)["occurrences"] == 1


def test_phrase_does_not_match_across_a_page_boundary():
    """Deliberate: page text is never joined, so a phrase split across
    two pages is not a match. Prevents false positives at page joins."""
    document = _pdf_doc(["ends with configuration", "workflow starts here"])
    result = _service().process(document, {"query": "configuration workflow"})
    assert result.status == "ok"
    # Scoped to the lexical pass: Phase 2 may add semantic findings here
    # independently of whether the phrase matched literally.
    assert _lexical_findings(result) == []


def test_phrase_collapses_runs_of_whitespace():
    document = _pdf_doc(["the OSS   \n  database is here"])
    result = _service().process(document, {"query": "OSS database"})
    assert _summary(result)["occurrences"] == 1


# --- token matching ----------------------------------------------------


def test_matching_is_case_insensitive_in_both_directions():
    document = _pdf_doc(["Authentication failed. Retry AUTHENTICATION now."])
    lower = _service().process(document, {"query": "authentication"})
    upper = _service().process(document, {"query": "AUTHENTICATION"})
    assert _summary(lower)["occurrences"] == 2
    assert _summary(upper)["occurrences"] == 2


def test_does_not_match_inside_a_longer_word():
    document = _pdf_doc(["reauthentication differs from authentication."])
    result = _service().process(document, {"query": "authentication"})
    assert _summary(result)["occurrences"] == 1


def test_matches_tokens_containing_punctuation():
    document = _pdf_doc(["Logged ERR#01 twice: ERR#01."])
    result = _service().process(document, {"query": "ERR#01"})
    assert _summary(result)["occurrences"] == 2


def test_regex_metacharacters_in_query_are_literal():
    document = _pdf_doc(["written in c++ here"])
    result = _service().process(document, {"query": "c++"})
    assert result.status == "ok"
    assert _summary(result)["occurrences"] == 1


def test_regex_metacharacter_query_does_not_match_everything():
    document = _pdf_doc(["no dots or stars in this line"])
    result = _service().process(document, {"query": ".*"})
    assert result.status == "ok"
    # Scoped to the lexical pass: the point is that ".*" is treated as a
    # literal and matches nothing, not that semantic returns nothing.
    assert _lexical_findings(result) == []


# --- empty and malformed input -----------------------------------------


def test_zero_matches_returns_ok_and_no_findings():
    # Updated for Phase 2. This originally asserted `result.findings == []`,
    # but semantic search now contributes findings independently of the
    # lexical pass — a query like "login" is meant to surface a paragraph
    # about authentication even with no exact match. So the assertion is
    # scoped to the lexical result: zero occurrences and no lexical
    # findings, while allowing semantic findings when semantic is
    # available.
    document = _pdf_doc(["nothing relevant here"])
    result = _service().process(document, {"query": "authentication"})
    assert result.status == "ok"
    assert result.meta["occurrences"] == 0
    lexical = [
        f for f in result.findings if f.details["match_type"].startswith("lexical")
    ]
    assert lexical == []


def test_whitespace_only_query_returns_no_findings():
    document = _pdf_doc(["authentication"])
    result = _service().process(document, {"query": "   \n\t "})
    assert result.status == "ok"
    assert result.findings == []


def test_missing_and_none_options_return_no_findings():
    document = _pdf_doc(["authentication"])
    service = _service()
    assert service.process(document, None).findings == []
    assert service.process(document, {}).findings == []
    assert service.process(document, {"query": None}).findings == []


def test_non_string_query_fails_cleanly_without_raising():
    document = _pdf_doc(["authentication"])
    result = _service().process(document, {"query": 123})
    assert result.status == "failed"
    assert result.findings == []
    assert "int" in (result.error or "")


def test_non_mapping_options_fails_cleanly_without_raising():
    document = _pdf_doc(["authentication"])
    result = _service().process(document, ["query"])
    assert result.status == "failed"
    assert "list" in (result.error or "")


# --- multi-page, locality, snippets ------------------------------------


def test_multi_page_aggregates_totals_and_sorted_unique_pages():
    document = _pdf_doc(["hit", "nothing", "hit hit"])
    result = _service().process(document, {"query": "hit"})
    summary = _summary(result)
    assert summary["occurrences"] == 3
    assert summary["pages"] == [1, 3]
    units = _unit_findings(result)
    assert [f.page for f in units] == [1, 3]
    assert [f.details["occurrences"] for f in units] == [1, 2]


def test_docx_paragraph_locality_is_preserved():
    document = _docx_doc(
        ["authentication overview", "unrelated text", "more authentication detail"]
    )
    result = _service().process(document, {"query": "authentication"})
    summary = _summary(result)
    assert summary["occurrences"] == 2
    assert summary["pages"] == [1]
    indices = [f.details["paragraph_index"] for f in _unit_findings(result)]
    assert indices == [0, 2]


def test_pages_and_paragraphs_are_not_double_counted():
    """Mirrors the shape used by tests/test_contract.py: a document
    carrying both pages and paragraphs holding the same text."""
    text = "Authentication failed. Retry authentication after refresh."
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    result = _service().process(document, {"query": "authentication"})
    assert _summary(result)["occurrences"] == 2


def test_each_unit_gets_its_own_snippet():
    document = _pdf_doc(["alpha authentication alpha", "beta authentication beta"])
    result = _service().process(document, {"query": "authentication"})
    snippets = [f.details["snippet"] for f in _unit_findings(result)]
    assert len(snippets) == 2
    assert "alpha" in snippets[0]
    assert "beta" in snippets[1]


def test_snippet_has_no_ellipsis_when_the_unit_is_short():
    document = _pdf_doc(["authentication"])
    result = _service().process(document, {"query": "authentication"})
    assert _summary(result)["snippet"] == "authentication"


def test_snippet_is_elided_and_whitespace_normalised_when_long():
    document = _pdf_doc(["x " * 200 + "authentication" + " y" * 200])
    result = _service().process(document, {"query": "authentication"})
    snippet = _summary(result)["snippet"]
    assert result.status == "ok"
    assert snippet.startswith("...")
    assert snippet.endswith("...")
    assert "\n" not in snippet
    assert "  " not in snippet


# --- finding layout and report columns ---------------------------------


def test_first_finding_is_the_aggregate_summary():
    document = _pdf_doc(["hit", "hit"])
    result = _service().process(document, {"query": "hit"})
    assert result.findings[0].details["match_type"] == "lexical_summary"
    assert result.findings[0].details["occurrences"] == 2
    assert all(f.details["match_type"] == "lexical" for f in _unit_findings(result))


def test_report_columns_cover_every_details_key_written():
    document = _docx_doc(["authentication here", "and authentication there"])
    result = _service().process(document, {"query": "authentication"})
    columns = set(_service().report_columns())
    assert result.findings
    for finding in result.findings:
        assert set(finding.details) <= columns
