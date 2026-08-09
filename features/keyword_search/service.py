"""Keyword search — lexical implementation.

Counts occurrences of the query, reports the pages it appears on and a
snippet of surrounding text. Purely local string matching: no models, no
network calls.

Semantic search (BGE embeddings + FAISS) is a planned upgrade — see the
TODO in _ensure_model below. It is not wired into process() yet.
"""
from __future__ import annotations

from typing import Optional

from common.contracts import Document, Finding, FeatureResult

_SNIPPET_RADIUS = 40


class KeywordSearchService:
    name = "keyword_search"

    def __init__(self) -> None:
        self._model = None  # lazily loaded; see _ensure_model

    def is_available(self) -> bool:
        return True

    def supports(self, document: Document) -> bool:
        return True

    def _ensure_model(self):
        """Lazily load the semantic search model, once per instance.

        TODO: replace/augment lexical matching with BGE embeddings + a
        FAISS index for semantic search, e.g.:

            if self._model is None:
                from sentence_transformers import SentenceTransformer
                self._model = SentenceTransformer("BAAI/bge-small-en-v1.5")
            return self._model

        Not called from process() yet — lexical search doesn't need it.
        """
        return self._model

    def process(self, document: Document, options: Optional[dict] = None) -> FeatureResult:
        try:
            options = options or {}
            query = (options.get("query") or "").strip()
            findings: list[Finding] = []

            if query:
                query_lower = query.lower()
                pages_with_counts: dict[int, int] = {}
                for page in document.pages:
                    count = page.text.lower().count(query_lower)
                    if count:
                        pages_with_counts[page.number] = count

                total = sum(pages_with_counts.values())
                if total:
                    ordered_pages = sorted(pages_with_counts)
                    first_page = next(
                        p for p in document.pages if p.number == ordered_pages[0]
                    )
                    findings.append(
                        Finding(
                            feature=self.name,
                            severity="info",
                            page=ordered_pages[0],
                            message=(
                                f"{query!r} found {total} time(s) across "
                                f"{len(ordered_pages)} page(s)"
                            ),
                            details={
                                "keyword": query,
                                "occurrences": total,
                                "pages": ordered_pages,
                                "snippet": _make_snippet(first_page.text, query_lower),
                            },
                        )
                    )

            return FeatureResult(feature=self.name, status="ok", findings=findings)
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        return ["keyword", "occurrences", "pages", "snippet"]


def _make_snippet(text: str, query_lower: str) -> str:
    lower = text.lower()
    idx = lower.find(query_lower)
    if idx == -1:
        return ""
    start = max(0, idx - _SNIPPET_RADIUS)
    end = min(len(text), idx + len(query_lower) + _SNIPPET_RADIUS)
    snippet = text[start:end].replace("\n", " ").strip()
    prefix = "..." if start > 0 else ""
    suffix = "..." if end < len(text) else ""
    return f"{prefix}{snippet}{suffix}"
