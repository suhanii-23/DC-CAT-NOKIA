"""Contract-level tests shared across all three features.

These tests enforce the inter-team agreement: every feature must return a
valid FeatureResult, must never raise, and the specific "never invent"
guarantees called out for broken_links and spell_check.
"""
from __future__ import annotations

import pytest

from common.contracts import Document, Heading, LinkAnnotation, Page, Paragraph
from features.broken_links.service import BrokenLinksService
from features.keyword_search.service import KeywordSearchService
from features.spell_check.service import SpellCheckService

FEATURES = [BrokenLinksService(), KeywordSearchService(), SpellCheckService()]
VALID_STATUSES = {"ok", "failed", "skipped"}


def _empty_document() -> Document:
    return Document(path="empty.pdf", format="pdf", page_count=0)


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.name)
def test_process_returns_a_valid_feature_result(feature):
    result = feature.process(_empty_document(), {"query": "authentication"})
    assert result.status in VALID_STATUSES
    assert result.feature == feature.name
    assert isinstance(result.findings, list)


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.name)
def test_process_never_raises_on_empty_document(feature):
    result = feature.process(_empty_document(), {"query": "x"})
    assert result.status in VALID_STATUSES


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.name)
def test_process_never_raises_with_options_none(feature):
    result = feature.process(_empty_document(), None)
    assert result.status in VALID_STATUSES


@pytest.mark.parametrize("feature", FEATURES, ids=lambda f: f.name)
def test_report_columns_is_a_list_of_strings(feature):
    columns = feature.report_columns()
    assert isinstance(columns, list)
    assert all(isinstance(c, str) for c in columns)


def test_broken_links_never_suggests_a_heading_absent_from_document():
    headings = [Heading(text="Introduction", level=1, number="1", page=1)]
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=2,
        pages=[Page(number=1, text=""), Page(number=2, text="")],
        headings=headings,
        links=[
            LinkAnnotation(
                page=1,
                text="See Section 9.9",
                target_name="section9_9",
                is_internal=True,
            )
        ],
    )
    result = BrokenLinksService().process(document, None)
    assert result.status == "ok"
    known_texts = {h.text for h in headings}
    for finding in result.findings:
        suggested = finding.details.get("suggested_heading")
        if suggested is not None:
            assert suggested in known_texts


def test_broken_links_confidence_levels():
    headings = [
        Heading(text="Troubleshooting", level=1, number="3", page=3),
        Heading(text="OSS Database Errors", level=2, number="3.1", page=3),
    ]
    links = [
        LinkAnnotation(page=3, text="See Section 3.1", target_name="s31", is_internal=True),
        LinkAnnotation(page=3, text="See Section 3.2", target_name="s32", is_internal=True),
    ]
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=3,
        pages=[Page(number=i, text="") for i in (1, 2, 3)],
        headings=headings,
        links=links,
    )
    result = BrokenLinksService().process(document, None)
    by_text = {f.details["link_text"]: f for f in result.findings}
    assert by_text["See Section 3.1"].details["suggestion_confidence"] == 0.95
    assert by_text["See Section 3.2"].details["suggestion_confidence"] == 0.72


def test_broken_links_flags_out_of_range_page_target():
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=2,
        pages=[Page(number=1, text=""), Page(number=2, text="")],
        headings=[],
        links=[
            LinkAnnotation(page=1, text="See Section 9", target_page=99, is_internal=True)
        ],
    )
    result = BrokenLinksService().process(document, None)
    assert result.status == "ok"
    assert len(result.findings) == 1
    assert result.findings[0].details["reason"] == "target page out of range"


def test_spell_check_never_flags_nokia_terms():
    terms = ["gNodeB", "MOCN", "RSRP", "X2", "ERR#01", "airscale_rnc"]
    text = "The " + " and ".join(terms) + " values were logged by the system."
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    result = SpellCheckService().process(document, None)
    assert result.status == "ok"
    flagged = {f.details["word"].lower() for f in result.findings}
    for term in terms:
        assert term.lower() not in flagged


def test_spell_check_flags_real_word_error():
    text = "The parameter was retrieved form the OSS database."
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    result = SpellCheckService().process(document, None)
    assert result.status == "ok"
    flagged = {(f.details["word"], f.details["suggestion"]) for f in result.findings}
    assert ("form", "from") in flagged


def test_keyword_search_counts_occurrences_and_pages():
    text = "Authentication failed. Retry authentication after refresh."
    document = Document(
        path="doc.pdf",
        format="pdf",
        page_count=1,
        pages=[Page(number=1, text=text)],
        paragraphs=[Paragraph(text=text, page=1, index=0)],
    )
    result = KeywordSearchService().process(document, {"query": "authentication"})
    assert result.status == "ok"
    assert result.findings[0].details["occurrences"] == 2
    assert result.findings[0].details["pages"] == [1]


def test_keyword_search_no_query_returns_no_findings():
    document = _empty_document()
    result = KeywordSearchService().process(document, {"query": ""})
    assert result.status == "ok"
    assert result.findings == []
