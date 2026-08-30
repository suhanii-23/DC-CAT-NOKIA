"""Multi-document keyword search: one exact keyword, many documents.

Purely lexical and completely separate from features/keyword_search/,
which stays frozen and is never imported from here.
"""
from features.multi_doc_keyword_search.service import (
    DocumentMatches,
    MultiDocKeywordSearchService,
    MultiDocSearchResult,
)

__all__ = [
    "DocumentMatches",
    "MultiDocKeywordSearchService",
    "MultiDocSearchResult",
]
