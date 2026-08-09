"""Broken internal-link detection — the worked example feature.

Flags internal links whose target page is out of range, and internal
links to named destinations that don't exist. Where possible, suggests a
replacement heading — but only from headings that actually exist in
document.headings. It never invents a heading, page, figure or table
number: if the evidence is weak, it returns no suggestion.
"""
from __future__ import annotations

import re
from typing import Optional

from common.contracts import Document, Finding, FeatureResult, Heading

_REFERENCE_RE = re.compile(
    r"\b(Section|Clause|Figure|Table|Appendix|Chapter)\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)",
    re.IGNORECASE,
)

_EXACT_MATCH_CONFIDENCE = 0.95
_SIBLING_MATCH_CONFIDENCE = 0.72


class BrokenLinksService:
    name = "broken_links"

    def __init__(self) -> None:
        pass  # no model: this feature is pure rule-based

    def is_available(self) -> bool:
        return True

    def supports(self, document: Document) -> bool:
        return True

    def process(self, document: Document, options: Optional[dict] = None) -> FeatureResult:
        try:
            findings: list[Finding] = []
            for link in document.links:
                if not link.is_internal:
                    continue

                reason = _broken_reason(link, document.page_count)
                if reason is None:
                    continue

                reference_type = _classify_reference_type(link.text)
                suggestion, confidence = _suggest_heading(link.text, document.headings)

                findings.append(
                    Finding(
                        feature=self.name,
                        severity="warning",
                        page=link.page,
                        message=(
                            f"Broken {reference_type or 'internal'} reference "
                            f"{link.text!r} ({reason})"
                        ),
                        confidence=confidence,
                        details={
                            "reference_type": reference_type,
                            "link_text": link.text,
                            "reason": reason,
                            "suggested_heading": suggestion.text if suggestion else None,
                            "suggested_heading_number": (
                                suggestion.number if suggestion else None
                            ),
                            "suggested_page": suggestion.page if suggestion else None,
                            "suggestion_confidence": confidence,
                        },
                    )
                )

            return FeatureResult(feature=self.name, status="ok", findings=findings)
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        return [
            "reference_type",
            "link_text",
            "reason",
            "suggested_heading",
            "suggested_heading_number",
            "suggested_page",
            "suggestion_confidence",
        ]


def _broken_reason(link, page_count: int) -> Optional[str]:
    if link.target_page is not None:
        if link.target_page < 1 or link.target_page > page_count:
            return "target page out of range"
        return None
    if link.target_name is not None:
        return "named destination not found"
    return None


def _classify_reference_type(text: str) -> Optional[str]:
    match = _REFERENCE_RE.search(text)
    if not match:
        return None
    return match.group(1).capitalize()


def _parse_number(number: str) -> Optional[tuple[int, ...]]:
    parts = number.split(".")
    try:
        return tuple(int(p) for p in parts)
    except ValueError:
        return None


def _is_adjacent_sibling(a: tuple[int, ...], b: tuple[int, ...]) -> bool:
    if len(a) != len(b) or not a:
        return False
    if a[:-1] != b[:-1]:
        return False
    return abs(a[-1] - b[-1]) == 1


def _suggest_heading(
    link_text: str, headings: list[Heading]
) -> tuple[Optional[Heading], Optional[float]]:
    match = _REFERENCE_RE.search(link_text)
    if not match:
        return None, None

    target = _parse_number(match.group(2))
    if target is None:
        return None, None

    sibling: Optional[Heading] = None
    for heading in headings:
        if not heading.number:
            continue
        candidate = _parse_number(heading.number)
        if candidate is None:
            continue
        if candidate == target:
            return heading, _EXACT_MATCH_CONFIDENCE
        if sibling is None and _is_adjacent_sibling(candidate, target):
            sibling = heading

    if sibling is not None:
        return sibling, _SIBLING_MATCH_CONFIDENCE
    return None, None
