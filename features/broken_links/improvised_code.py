"""Broken internal-link detection — improved version.

Flags internal links whose target page is out of range, and internal
links to named destinations that don't exist. Where possible, suggests a
replacement heading — but only from headings (or figure/table captions)
that actually exist in the document. It never invents a heading, page,
figure or table number: if the evidence is weak, it returns no
suggestion.

Changes vs. the original:
  - Named-destination links are only flagged broken if the name is
    actually missing from the document, instead of unconditionally.
  - Added a fuzzy text-similarity fallback (stdlib difflib, no new
    dependency) for headings that were renamed rather than renumbered.
  - Sibling matching now tolerates any numeric distance, with confidence
    decaying as the distance grows, instead of only accepting +/-1.
  - Suggestions are now ranked and the top 3 candidates are returned
    (primary suggestion + up to 2 alternatives), matching the proposal's
    "alternative_matches" behaviour.
  - Figure/Table references now prefer document.figures / document.tables
    if those lists exist on the Document contract, falling back to
    headings if not (kept defensive via getattr so this doesn't break
    if the contract hasn't been extended yet).
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Optional

from common.contracts import Document, Finding, FeatureResult, Heading

_REFERENCE_RE = re.compile(
    r"\b(Section|Clause|Figure|Table|Appendix|Chapter)\s+([A-Za-z0-9]+(?:\.[A-Za-z0-9]+)*)",
    re.IGNORECASE,
)

_EXACT_MATCH_CONFIDENCE = 0.95
_SIBLING_BASE_CONFIDENCE = 0.80
_SIBLING_DECAY_PER_STEP = 0.08  # confidence drops as numeric distance grows
_SIBLING_MIN_CONFIDENCE = 0.50
_FUZZY_MIN_RATIO = 0.72  # below this, we don't trust a text-only match
_FUZZY_CONFIDENCE_FLOOR = 0.55
_FUZZY_CONFIDENCE_CEILING = 0.78
_MAX_ALTERNATIVES = 2  # plus the primary suggestion = top 3 total


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
            named_destinations = set(getattr(document, "named_destinations", []) or [])

            for link in document.links:
                if not link.is_internal:
                    continue

                reason = _broken_reason(link, document.page_count, named_destinations)
                if reason is None:
                    continue

                reference_type = _classify_reference_type(link.text)
                candidates = _search_headings(document, reference_type, link.text)

                primary = candidates[0] if candidates else None
                alternatives = candidates[1 : 1 + _MAX_ALTERNATIVES]

                findings.append(
                    Finding(
                        feature=self.name,
                        severity="warning",
                        page=link.page,
                        message=(
                            f"Broken {reference_type or 'internal'} reference "
                            f"{link.text!r} ({reason})"
                        ),
                        confidence=primary.confidence if primary else None,
                        details={
                            "reference_type": reference_type,
                            "link_text": link.text,
                            "reason": reason,
                            "suggested_heading": primary.heading.text if primary else None,
                            "suggested_heading_number": (
                                primary.heading.number if primary else None
                            ),
                            "suggested_page": primary.heading.page if primary else None,
                            "suggestion_confidence": primary.confidence if primary else None,
                            "match_method": primary.method if primary else None,
                            "alternative_matches": [
                                {
                                    "destination": alt.heading.text,
                                    "number": alt.heading.number,
                                    "page": alt.heading.page,
                                    "confidence": alt.confidence,
                                    "method": alt.method,
                                }
                                for alt in alternatives
                            ],
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
            "match_method",
            "alternative_matches",
        ]


def _broken_reason(link, page_count: int, named_destinations: set) -> Optional[str]:
    if link.target_page is not None:
        if link.target_page < 1 or link.target_page > page_count:
            return "target page out of range"
        return None
    if link.target_name is not None:
        # Previously this branch always reported "broken" regardless of
        # whether the name actually existed. Now it only flags a real miss.
        if link.target_name not in named_destinations:
            return "named destination not found"
        return None
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


def _numeric_distance(a: tuple[int, ...], b: tuple[int, ...]) -> Optional[int]:
    """Return how far apart two same-length, same-parent numbers are.

    Returns None if they aren't comparable siblings (different length or
    different parent path), otherwise the absolute distance of the last
    component (e.g. 3.2 vs 3.5 -> 3).
    """
    if len(a) != len(b) or not a:
        return None
    if a[:-1] != b[:-1]:
        return None
    return abs(a[-1] - b[-1])


class _Candidate:
    __slots__ = ("heading", "confidence", "method")

    def __init__(self, heading: Heading, confidence: float, method: str) -> None:
        self.heading = heading
        self.confidence = confidence
        self.method = method


def _candidate_pool(document: Document, reference_type: Optional[str]) -> list[Heading]:
    """Prefer figure/table caption lists when they exist, else fall back
    to headings. Defensive via getattr so this doesn't break against an
    older Document contract that hasn't added those fields yet.
    """
    if reference_type == "Figure":
        figures = getattr(document, "figures", None)
        if figures:
            return figures
    if reference_type == "Table":
        tables = getattr(document, "tables", None)
        if tables:
            return tables
    return document.headings


def _search_headings(
    document: Document, reference_type: Optional[str], link_text: str
) -> list[_Candidate]:
    match = _REFERENCE_RE.search(link_text)
    pool = _candidate_pool(document, reference_type)

    candidates: list[_Candidate] = []

    target = _parse_number(match.group(2)) if match else None

    if target is not None:
        for heading in pool:
            if not heading.number:
                continue
            candidate_number = _parse_number(heading.number)
            if candidate_number is None:
                continue
            if candidate_number == target:
                candidates.append(_Candidate(heading, _EXACT_MATCH_CONFIDENCE, "exact_number"))
                continue
            distance = _numeric_distance(candidate_number, target)
            if distance is not None and distance > 0:
                confidence = max(
                    _SIBLING_MIN_CONFIDENCE,
                    _SIBLING_BASE_CONFIDENCE - (distance - 1) * _SIBLING_DECAY_PER_STEP,
                )
                candidates.append(_Candidate(heading, round(confidence, 2), "renumbered_sibling"))

    # If nothing numeric matched (or there was no number at all, e.g. a
    # heading was renamed), fall back to fuzzy text similarity so a
    # renamed section still gets a usable suggestion.
    if not any(c.method in ("exact_number", "renumbered_sibling") for c in candidates):
        reference_text = _strip_reference_prefix(link_text)
        for heading in pool:
            ratio = SequenceMatcher(None, reference_text.lower(), heading.text.lower()).ratio()
            if ratio >= _FUZZY_MIN_RATIO:
                confidence = _FUZZY_CONFIDENCE_FLOOR + ratio * (
                    _FUZZY_CONFIDENCE_CEILING - _FUZZY_CONFIDENCE_FLOOR
                )
                candidates.append(_Candidate(heading, round(confidence, 2), "fuzzy_text"))

    candidates.sort(key=lambda c: c.confidence, reverse=True)
    return candidates


def _strip_reference_prefix(text: str) -> str:
    """Remove leading 'See Section 3.2' style prefixes so fuzzy matching
    compares the meaningful part of the reference, not boilerplate.
    """
    return _REFERENCE_RE.sub("", text).strip(" -:\u2013\u2014")
