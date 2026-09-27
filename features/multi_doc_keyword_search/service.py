"""Multi-document keyword search — one exact keyword, across many documents.

What it is
----------
The user supplies **one keyword**. Every eligible document is searched for
that keyword and **every** occurrence is returned, grouped by document,
with page and surrounding context. The search never stops at the first
document or the first hit.

What it is not
--------------
Not semantic search. No embeddings, no vector index, no similarity, no
LLM, no synonyms, no query expansion, no fuzzy matching. Searching
"authentication" searches for "authentication" and nothing else. See
features/multi_doc_keyword_search/matcher.py for the matching rules.

How it differs from features/keyword_search/
--------------------------------------------
That feature is a separate, frozen feature and is not touched, imported,
or altered by this one. It searches **one** document and reports lexical
occurrence *counts* per unit alongside BGE/FAISS semantic passages. This
feature searches **many** documents, is purely lexical, and emits **one
finding per occurrence** so that "5 hits in doc A + 2 in doc B" comes
back as 7 findings rather than 2 aggregates.

Counting unit
-------------
Paragraphs when the document has them, pages otherwise — never both.
common/parser.py derives paragraphs *from* page text, so searching both
would double-count every match. Paragraphs are preferred because they
preserve locality for DOCX, where every page number is 1.

Reading documents from disk
---------------------------
`search()` reads a PDF's page text directly with PyMuPDF instead of calling
common.parser.parse(). The full parser also derives paragraphs from line
geometry, links, the outline and named destinations, none of which a
keyword search uses. On a 748-page scanned book that geometry pass alone
took about 120 s, against under 1 s for the page text. Pages are then the
search unit for PDFs, which gives the same matches: paragraphs are cut
from exactly this page text. DOCX still goes through the shared parser,
which is already fast for it.

Error handling
--------------
An empty keyword is a validation error, returned as status="failed".
A document that cannot be parsed or searched is recorded in `errors` and
the remaining documents are still searched. Nothing here raises: the
public entry points always return a result object.
"""
from __future__ import annotations

import os
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple, Optional, Union

import pymupdf as fitz

from common.contracts import Document, FeatureResult, Finding, Page
from common.parser import parse

from features.multi_doc_keyword_search.discovery import discover
from features.multi_doc_keyword_search.matcher import (
    EmptyKeywordError,
    Occurrence,
    compile_keyword,
    find_occurrences,
    normalise_keyword,
)

FEATURE_NAME = "multi_doc_keyword_search"

# Detail keys written onto every Finding. "page" is deliberately absent:
# common/excel.py already emits it as a base column.
_REPORT_COLUMNS = [
    "keyword",
    "document",
    "occurrence_index",
    "paragraph_index",
    "match_text",
    "context",
]


# A PDF page with an image and fewer extractable characters than this is
# treated as a scanned page. A text page carries thousands; a scanned book
# with a one-line watermark per page carries about 60. The image is
# required so that a genuinely short text page is never mistaken for one.
_SCANNED_PAGE_MAX_CHARS = 100


class _Unit(NamedTuple):
    """One searchable span of a document."""

    text: str
    page: int
    paragraph_index: Optional[int]


class KeywordMatch(NamedTuple):
    """One row of the keyword search report: where one occurrence is."""

    document: str  # file name, or the full path when two files share a name
    page: int
    keyword: str  # what the user searched for
    match: str  # the word as it appears in the document, casing kept
    context: str  # the surrounding sentence, verbatim


@dataclass
class DocumentMatches:
    """Every occurrence found in one document."""

    path: str
    format: Optional[str] = None
    page_count: int = 0
    findings: list[Finding] = field(default_factory=list)
    # Pages that are an image with next to no text (PDFs read from disk).
    scanned_pages: int = 0

    @property
    def match_count(self) -> int:
        return len(self.findings)

    @property
    def looks_scanned(self) -> bool:
        """Most pages are images without a text layer: probably a scan.

        Zero matches in such a document says nothing about its content,
        so callers should say so instead of reporting a clean "0".
        """
        return bool(self.page_count) and self.scanned_pages * 2 > self.page_count

    def to_dict(self, limit: Optional[int] = None) -> dict[str, Any]:
        findings = self.findings if limit is None else self.findings[:limit]
        payload: dict[str, Any] = {
            "document": self.path,
            "format": self.format,
            "page_count": self.page_count,
            "match_count": self.match_count,
            "matches": [
                {
                    "page": f.page,
                    "keyword": f.details["keyword"],
                    "match_text": f.details["match_text"],
                    "context": f.details["context"],
                    "paragraph_index": f.details["paragraph_index"],
                    "occurrence_index": f.details["occurrence_index"],
                }
                for f in findings
            ],
        }
        if limit is not None and self.match_count > limit:
            payload["truncated"] = True
        return payload


@dataclass
class MultiDocSearchResult:
    """The aggregate outcome of one multi-document keyword search."""

    keyword: str
    status: str  # "ok" | "failed"
    documents: list[DocumentMatches] = field(default_factory=list)
    errors: list[dict[str, str]] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def documents_searched(self) -> int:
        """Documents that were successfully parsed and searched."""
        return len(self.documents)

    @property
    def documents_with_matches(self) -> int:
        return sum(1 for doc in self.documents if doc.match_count)

    @property
    def total_matches(self) -> int:
        return sum(doc.match_count for doc in self.documents)

    def findings(self) -> list[Finding]:
        """Every finding from every document, in document order."""
        return [f for doc in self.documents for f in doc.findings]

    def rows(self) -> list[KeywordMatch]:
        """Every occurrence as a report row, in document then reading order.

        Documents are named by file name. Two different files with the same
        name (reached through different folders) keep their full paths, so
        no row is attributed ambiguously.
        """
        names = self.document_names()
        return [
            KeywordMatch(
                document=names[doc.path],
                page=f.page,
                keyword=self.keyword,
                match=f.details["match_text"],
                context=f.details["context"],
            )
            for doc in self.documents
            for f in doc.findings
        ]

    def document_names(self) -> dict[str, str]:
        """Path -> the name `rows()` shows for that document."""
        return _display_names([doc.path for doc in self.documents])

    def to_dict(self, limit_per_document: Optional[int] = None) -> dict[str, Any]:
        """JSON-ready payload.

        Counts always reflect the whole result, even when the per-document
        match lists are truncated for size.
        """
        payload: dict[str, Any] = {
            "status": self.status,
            "keyword": self.keyword,
            "documents_searched": self.documents_searched,
            "documents_with_matches": self.documents_with_matches,
            "total_matches": self.total_matches,
            "documents": [doc.to_dict(limit_per_document) for doc in self.documents],
        }
        if self.errors:
            payload["errors"] = list(self.errors)
        if self.error:
            payload["error"] = self.error
        return payload

    def to_feature_result(self) -> FeatureResult:
        """One FeatureResult over all documents, for common/excel.py."""
        return FeatureResult(
            feature=FEATURE_NAME,
            status=self.status,
            findings=self.findings(),
            error=self.error,
            meta={
                "keyword": self.keyword,
                "documents_searched": self.documents_searched,
                "documents_with_matches": self.documents_with_matches,
                "total_matches": self.total_matches,
                "errors": list(self.errors),
            },
        )


class MultiDocKeywordSearchService:
    """Multi-document literal keyword search.

    Implements the common.contracts.FeatureModule protocol (so one already
    parsed document can be searched through the same code path and
    reported through common/excel.py), and adds `search()` /
    `search_documents()` as the multi-document entry points.

    Stateless and cheap to construct: there is no model to load.
    """

    name = FEATURE_NAME

    def __init__(self) -> None:
        pass  # no model, no cache: matching is a compiled regex

    # --- FeatureModule protocol ---------------------------------------

    def is_available(self) -> bool:
        return True  # pure stdlib matching over an already-parsed Document

    def supports(self, document: Document) -> bool:
        return True

    def process(
        self, document: Document, options: Optional[dict] = None
    ) -> FeatureResult:
        """Search one already-parsed document. Never raises.

        options: {"keyword": "<the keyword>"}
        """
        try:
            keyword = normalise_keyword((options or {}).get("keyword"))
        except (EmptyKeywordError, TypeError) as exc:
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

        try:
            pattern = compile_keyword(keyword)
            matches = _search_document(document, keyword, pattern)
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

        return FeatureResult(
            feature=self.name,
            status="ok",
            findings=matches.findings,
            meta={
                "keyword": keyword,
                "document": matches.path,
                "total_matches": matches.match_count,
            },
        )

    def report_columns(self) -> list[str]:
        return list(_REPORT_COLUMNS)

    # --- multi-document entry points -----------------------------------

    def search(
        self, targets: Union[str, Iterable[str]], keyword: str
    ) -> MultiDocSearchResult:
        """Search every document under `targets` for one keyword.

        `targets` is a file path, a folder path, or an iterable of either.
        Folders are walked recursively for .pdf/.docx. Each document is
        parsed exactly once; a document that fails to parse is recorded in
        `errors` and the search continues with the rest.
        """
        try:
            keyword = normalise_keyword(keyword)
        except (EmptyKeywordError, TypeError) as exc:
            return MultiDocSearchResult(
                keyword=keyword if isinstance(keyword, str) else "",
                status="failed",
                error=str(exc),
            )

        pattern = compile_keyword(keyword)
        found = discover(targets)

        result = MultiDocSearchResult(keyword=keyword, status="ok")
        result.errors = [
            {"document": target, "error": reason} for target, reason in found.skipped
        ]

        for path in found.paths:
            try:
                # Read one document at a time and dropped as soon as its
                # findings are extracted, so peak memory stays at roughly
                # one document regardless of how many are searched.
                document, scanned_pages = _read(path)
                matches = _search_document(document, keyword, pattern)
                matches.scanned_pages = scanned_pages
                result.documents.append(matches)
            except Exception as exc:
                result.errors.append({"document": path, "error": str(exc)})

        return result

    def search_documents(
        self, documents: Iterable[Document], keyword: str
    ) -> MultiDocSearchResult:
        """Same search over documents that are already parsed.

        Use this when the caller already holds Documents — it avoids
        parsing the same file twice.
        """
        try:
            keyword = normalise_keyword(keyword)
        except (EmptyKeywordError, TypeError) as exc:
            return MultiDocSearchResult(
                keyword=keyword if isinstance(keyword, str) else "",
                status="failed",
                error=str(exc),
            )

        pattern = compile_keyword(keyword)
        result = MultiDocSearchResult(keyword=keyword, status="ok")
        for document in documents:
            try:
                result.documents.append(_search_document(document, keyword, pattern))
            except Exception as exc:
                path = getattr(document, "path", "<unknown>")
                result.errors.append({"document": path, "error": str(exc)})
        return result


# --- reading one document ----------------------------------------------


def _read(path: str) -> tuple[Document, int]:
    """The text of one document, read once, plus its count of scanned pages.

    PDFs: page text only, straight from PyMuPDF (see the module docstring
    for why the full parser is skipped). Everything else: the shared parser,
    and a DOCX has no scanned pages.
    """
    if os.path.splitext(path)[1].lower() == ".pdf":
        return _read_pdf_pages(path)
    return parse(path), 0


def _read_pdf_pages(path: str) -> tuple[Document, int]:
    pages: list[Page] = []
    scanned_pages = 0
    with fitz.open(path) as pdf:
        if pdf.needs_pass:
            raise ValueError("password-protected PDF")
        for number, page in enumerate(pdf, start=1):
            text = page.get_text("text")
            pages.append(Page(number=number, text=text))
            if len(text.strip()) < _SCANNED_PAGE_MAX_CHARS and page.get_images():
                scanned_pages += 1
    document = Document(path=path, format="pdf", pages=pages, page_count=len(pages))
    return document, scanned_pages


def _display_names(paths: list[str]) -> dict[str, str]:
    """File name per path, or the full path where two files share a name."""
    names = {path: os.path.basename(path) for path in paths}
    counts = Counter(names.values())
    return {path: name if counts[name] == 1 else path for path, name in names.items()}


# --- searching one document --------------------------------------------


def _units(document: Document) -> list[_Unit]:
    """Spans to search: paragraphs when present, pages otherwise.

    Never both — the parser derives paragraphs from page text, so
    searching both would report every match twice.
    """
    if document.paragraphs:
        return [_Unit(p.text, p.page, p.index) for p in document.paragraphs]
    return [_Unit(page.text, page.number, None) for page in document.pages]


def _search_document(
    document: Document, keyword: str, pattern: re.Pattern
) -> DocumentMatches:
    """Every occurrence of the keyword in one document, in reading order."""
    matches = DocumentMatches(
        path=document.path,
        format=document.format,
        page_count=document.page_count,
    )
    occurrence_index = 0
    for unit in _units(document):
        for occurrence in find_occurrences(unit.text, pattern):
            occurrence_index += 1
            matches.findings.append(
                _finding(document, keyword, unit, occurrence, occurrence_index)
            )
    return matches


def _finding(
    document: Document,
    keyword: str,
    unit: _Unit,
    occurrence: Occurrence,
    occurrence_index: int,
) -> Finding:
    where = f"page {unit.page}"
    if unit.paragraph_index is not None:
        where += f", paragraph {unit.paragraph_index}"
    return Finding(
        feature=FEATURE_NAME,

        page=unit.page,
        message=f"{keyword!r} found on {where}",
        confidence=None,  # an exact match needs no similarity caveat
        details={
            "keyword": keyword,
            "document": document.path,
            "page": unit.page,
            "paragraph_index": unit.paragraph_index,
            # The text as it actually appears, so a case-insensitive hit
            # shows the reader which casing was found.
            "match_text": occurrence.text,
            # Verbatim document text. Never generated, never paraphrased.
            "context": occurrence.context,
            "occurrence_index": occurrence_index,  # 1-based, within this document
        },
    )
