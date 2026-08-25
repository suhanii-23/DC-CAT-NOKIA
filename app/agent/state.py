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