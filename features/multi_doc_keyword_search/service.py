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

Error handling
--------------
An empty keyword is a validation error, returned as status="failed".
A document that cannot be parsed or searched is recorded in `errors` and
the remaining documents are still searched. Nothing here raises: the
public entry points always return a result object.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Iterable, NamedTuple, Optional, Union

from common.contracts import Document, FeatureResult, Finding
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


class _Unit(NamedTuple):
    """One searchable span of a document."""

    text: str
    page: int
    paragraph_index: Optional[int]


@dataclass
class DocumentMatches:
    """Every occurrence found in one document."""

    path: str
    format: Optional[str] = None
    page_count: int = 0
    findings: list[Finding] = field(default_factory=list)

    @property
    def match_count(self) -> int:
        return len(self.findings)

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
                # Parsed one document at a time and dropped as soon as its
                # findings are extracted, so peak memory stays at roughly
                # one document regardless of how many are searched.
                document = parse(path)
                result.documents.append(_search_document(document, keyword, pattern))
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
        severity="info",
        page=unit.page,
        message=f"{keyword!r} found on {where} of {document.path}",
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
