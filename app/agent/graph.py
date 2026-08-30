from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from common.contracts import FeatureResult
from features.broken_links.service import BrokenLinksService
from features.keyword_search.service import KeywordSearchService
from features.multi_doc_keyword_search.service import MultiDocKeywordSearchService
from features.spell_check.service import SpellCheckService

from .state import AgentState, CorpusState


# Existing feature services
spell_check_service = SpellCheckService()
broken_links_service = BrokenLinksService()
keyword_search_service = KeywordSearchService()

# Corpus feature services — these run once over the whole document set,
# not once per document, so they belong to the corpus graph below.
multi_doc_keyword_search_service = MultiDocKeywordSearchService()


def run_spell_check(state: AgentState) -> dict[str, Any]:
    """Run the existing spell-check feature."""
    document = state["document"]
    options = state.get("options", {})

    if not spell_check_service.is_available():
        result = FeatureResult(
            feature=spell_check_service.name,
            status="skipped",
        )
    elif not spell_check_service.supports(document):
        result = FeatureResult(
            feature=spell_check_service.name,
            status="skipped",
        )
    else:
        result = spell_check_service.process(document, options)

    return {"spell_check": result}


def run_broken_links(state: AgentState) -> dict[str, Any]:
    """Run the existing broken-links feature."""
    document = state["document"]
    options = state.get("options", {})

    if not broken_links_service.is_available():
        result = FeatureResult(
            feature=broken_links_service.name,
            status="skipped",
        )
    elif not broken_links_service.supports(document):
        result = FeatureResult(
            feature=broken_links_service.name,
            status="skipped",
        )
    else:
        result = broken_links_service.process(document, options)

    return {"broken_links": result}


def run_keyword_search(state: AgentState) -> dict[str, Any]:
    """Run the existing keyword-search feature."""
    document = state["document"]
    options = state.get("options", {})

    if not keyword_search_service.is_available():
        result = FeatureResult(
            feature=keyword_search_service.name,
            status="skipped",
        )
    elif not keyword_search_service.supports(document):
        result = FeatureResult(
            feature=keyword_search_service.name,
            status="skipped",
        )
    else:
        result = keyword_search_service.process(document, options)

    return {"keyword_search": result}


def collect_results(state: AgentState) -> dict[str, Any]:
    """Collect results from the features that were selected."""

    results: list[FeatureResult] = []

    for feature_name in state.get("selected_features", []):
        result = state.get(feature_name)
        if result is not None:
            results.append(result)

    return {"results": results}


def route_selected_features(state: AgentState) -> list[str]:
    """Route only the features selected by the CLI."""

    selected = state.get("selected_features", [])

    routes: list[str] = []

    if "spell_check" in selected:
        routes.append("spell_check")

    if "broken_links" in selected:
        routes.append("broken_links")

    if "keyword_search" in selected:
        routes.append("keyword_search")

    return routes


def build_agent_graph():
    """Build the LangGraph agent that orchestrates selected features."""

    builder = StateGraph(AgentState)

    builder.add_node("spell_check", run_spell_check)
    builder.add_node("broken_links", run_broken_links)
    builder.add_node("keyword_search", run_keyword_search)
    builder.add_node("collect_results", collect_results)

    builder.add_conditional_edges(
        START,
        route_selected_features,
        {
            "spell_check": "spell_check",
            "broken_links": "broken_links",
            "keyword_search": "keyword_search",
        },
    )

    builder.add_edge("spell_check", "collect_results")
    builder.add_edge("broken_links", "collect_results")
    builder.add_edge("keyword_search", "collect_results")

    builder.add_edge("collect_results", END)

    return builder.compile()


agent_graph = build_agent_graph()


# --- corpus graph: features that run once over the whole document set ---


def run_multi_doc_keyword_search(state: CorpusState) -> dict[str, Any]:
    """Run multi-document keyword search over the whole corpus, once.

    Delegates entirely to MultiDocKeywordSearchService: no matching logic
    lives in the graph. The service parses each document itself and isolates
    per-document failures, so one unreadable file does not stop the rest.
    """
    paths = state.get("paths", [])
    options = state.get("options") or {}
    keyword = options.get("query")

    if not multi_doc_keyword_search_service.is_available():
        return {
            "multi_doc_keyword_search": FeatureResult(
                feature=multi_doc_keyword_search_service.name,
                status="skipped",
            )
        }

    if not keyword:
        # Nothing to search for. Skipped, not failed — this is the normal
        # case for a run that passes no --query at all.
        return {
            "multi_doc_keyword_search": FeatureResult(
                feature=multi_doc_keyword_search_service.name,
                status="skipped",
            )
        }

    search = multi_doc_keyword_search_service.search(paths, keyword)
    return {"multi_doc_keyword_search": search.to_feature_result()}


def collect_corpus_results(state: CorpusState) -> dict[str, Any]:
    """Collect results from the corpus features that were selected."""

    results: list[FeatureResult] = []

    for feature_name in state.get("selected_features", []):
        result = state.get(feature_name)
        if result is not None:
            results.append(result)

    return {"results": results}


def route_selected_corpus_features(state: CorpusState) -> list[str]:
    """Route only the corpus features selected by the CLI."""

    selected = state.get("selected_features", [])

    routes: list[str] = []

    if "multi_doc_keyword_search" in selected:
        routes.append("multi_doc_keyword_search")

    return routes


def build_corpus_graph():
    """Build the LangGraph agent that orchestrates corpus-wide features.

    Separate from agent_graph because the two are invoked differently:
    agent_graph runs once per document, this one runs once per run.
    """

    builder = StateGraph(CorpusState)

    builder.add_node("multi_doc_keyword_search", run_multi_doc_keyword_search)
    builder.add_node("collect_results", collect_corpus_results)

    builder.add_conditional_edges(
        START,
        route_selected_corpus_features,
        {"multi_doc_keyword_search": "multi_doc_keyword_search"},
    )

    builder.add_edge("multi_doc_keyword_search", "collect_results")

    builder.add_edge("collect_results", END)

    return builder.compile()


corpus_graph = build_corpus_graph()