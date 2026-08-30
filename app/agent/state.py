from __future__ import annotations

from typing import TypedDict

from common.contracts import Document, FeatureResult


class AgentState(TypedDict, total=False):
    document: Document
    options: dict
    selected_features: list[str]

    spell_check: FeatureResult
    broken_links: FeatureResult
    keyword_search: FeatureResult

    results: list[FeatureResult]


class CorpusState(TypedDict, total=False):
    """State for features that run once over the WHOLE set of documents.

    AgentState is per-document: the graph built on it is invoked once for
    each file. A corpus feature answers a question that only exists across
    documents ("how many of these mention X"), so it gets its own state and
    its own graph, invoked exactly once per run. Keeping them separate is
    what stops a corpus feature from silently executing once per document.

    `paths` rather than parsed Documents: the corpus services own their
    parsing so one unreadable file can be reported without taking the run
    down with it.
    """

    paths: list[str]
    options: dict
    selected_features: list[str]

    multi_doc_keyword_search: FeatureResult

    results: list[FeatureResult]