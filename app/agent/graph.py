from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from common.contracts import FeatureResult
from features.broken_links.service import BrokenLinksService
from features.keyword_search.service import KeywordSearchService
from features.spell_check.service import SpellCheckService

from .state import AgentState


# Existing feature services
spell_check_service = SpellCheckService()
broken_links_service = BrokenLinksService()
keyword_search_service = KeywordSearchService()


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