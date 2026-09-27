"""Broken internal-link detection — the worked example feature.

Flags internal links whose target page is out of range, and internal
links to named destinations that don't exist. Where possible, suggests a
replacement heading — but only from headings that actually exist in
document.headings. It never invents a heading, page, figure or table
number: if the evidence is weak, it returns no suggestion.

Evidence for *what* a link refers to is taken in order of reliability:
the named destination first ("Section_5.2"), then the visible link text,
then the paragraph the link sits in. The link rectangle rarely lines up
with the reference phrase, so anchor text alone is often truncated or
picks up neighbouring words ("the product. Se").
"""
from __future__ import annotations

import re
from typing import Optional

from common.contracts import Document, Finding, FeatureResult, Heading

# A reference is a keyword followed by a DESIGNATOR, not by any word. Without
# that constraint ordinary prose matches: "the table lists the options" was
# read as a reference to Table "lists". Sections, chapters, figures and tables
# are numbered; appendices take a letter or a number.
_REFERENCE_RE = re.compile(
    r"\b(?:"
    r"(?P<kind>Section|Clause|Chapter|Figure|Table)\s+(?P<number>\d+(?:\.\d+)*)"
    r"|(?P<akind>Appendix)\s+(?P<anumber>[A-Z]\b|\d+(?:\.\d+)*)"
    r")",
    re.IGNORECASE,
)

# A caption line introduces the thing a reference points at: "Table 5: Supported
# platforms". Collecting captions is what lets a Figure or Table reference be
# resolved at all — the heading list never contains them.
_CAPTION_RE = re.compile(
    r"^(?P<kind>Table|Figure)\s+(?P<number>\d+(?:[.\-]\d+)*)"
    r"\s*[:.\u2013\u2014-]?\s*(?P<title>\S.*)?$",
    re.IGNORECASE,
)

_CAPTIONED_TYPES = frozenset({"Figure", "Table"})

# --- Nokia-style cross-references -------------------------------------------
#
# Nokia documentation does not write "see Section 3.2". It links the section
# TITLE: "See Modifying XYZ parameters to find information on...". When such a
# reference breaks, the title disappears and leaves a gap in the sentence:
#
#     working : "See Modifying XYZ parameters to find information on..."
#     broken  : "See  to find information on..."
#     broken  : "For more information, see  in XYZ RNC Network."
#
# So the signal is a reference cue with nothing after it. Detected from the
# text, independently of link annotations, because a removed cross-reference
# usually takes its annotation with it.
#
# "see/refer to" is listed first so that "See/Refer to XYZ technical support
# note." — a reference to another document, not a cross-reference — consumes
# the "to" and is left alone. Nokia asked for those to be ignored.
_REFERENCE_CUE_RE = re.compile(
    r"\b(?P<cue>see\s*/\s*refer(?:s|red)?\s+to|see\s+also|refer(?:s|red)?\s+to"
    r"|see|described\s+in|shown\s+in|depicted\s+in)(?P<gap>[ \t]*)",
    re.IGNORECASE,
)

# A cross-reference title never begins with one of these. If one follows the
# cue directly, whatever sat between them has been removed.
_FUNCTION_WORDS = frozenset({
    "to", "in", "for", "on", "at", "of", "and", "or", "as", "from",
})

_NEXT_TOKEN_RE = re.compile(r"([A-Za-z0-9:/'\"\-]+)")

# Reference types that name a heading in the document outline. Figure and
# Table references point at captions, which are not headings, so matching
# their number against heading numbers would be wrong: "Figure 3" is not
# "Section 3".
_HEADING_REFERENCE_TYPES = frozenset({"Section", "Clause", "Chapter", "Appendix"})

_EXACT_MATCH_CONFIDENCE = 0.95
_SIBLING_MATCH_CONFIDENCE = 0.72

# How much of the (possibly truncated) anchor text to use when locating the
# paragraph a link sits in.
_SNIPPET_LEN = 12


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
            captions = _caption_index(document)
            reported: set[tuple[int, str, str]] = set()

            for link in document.links:
                if not link.is_internal:
                    continue

                reason = _broken_reason(link, document.page_count)
                if reason is None:
                    continue

                reference_text, evidence_source = _reference_text(link, document)
                reference = _find_reference(reference_text)
                reference_type = reference[0] if reference else None

                suggestion, confidence = _suggest_heading(
                    reference_text, reference_type, document.headings
                )
                suggested_text = suggestion.text if suggestion else None
                suggested_number = suggestion.number if suggestion else None
                suggested_page = suggestion.page if suggestion else None

                if suggestion is None:
                    # Figures and tables live in captions, not headings.
                    caption_text, caption_page, caption_confidence = _suggest_caption(
                        reference, captions
                    )
                    if caption_text is not None:
                        suggested_text = caption_text
                        suggested_page = caption_page
                        confidence = caption_confidence

                if reference is not None:
                    reported.add((link.page, reference[0], reference[1]))

                findings.append(
                    Finding(
                        feature=self.name,

                        page=link.page,
                        message=(
                            f"Broken {reference_type or 'internal'} reference "
                            f"{_display(reference_text)!r} ({reason})"
                        ),
                        confidence=confidence,
                        details={
                            "reference_type": reference_type,
                            "reference_text": _display(reference_text),
                            "evidence_source": evidence_source,
                            "link_text": link.text,
                            "reason": reason,
                            "suggested_heading": suggested_text,
                            "suggested_heading_number": suggested_number,
                            "suggested_page": suggested_page,
                            "suggestion_confidence": confidence,
                        },
                    )
                )

            findings.extend(_prose_findings(document, captions, reported))
            findings.extend(_missing_reference_findings(document))

            return FeatureResult(feature=self.name, status="ok", findings=findings)
        except Exception as exc:  # process() must never raise
            return FeatureResult(feature=self.name, status="failed", error=str(exc))

    def report_columns(self) -> list[str]:
        return [
            "reference_type",
            "reference_text",
            "evidence_source",
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


def _reference_text(link, document: Document) -> tuple[str, str]:
    """Best available evidence for what this link was meant to point at.

    Returns (text, evidence_source). Nothing here invents content: every
    candidate is taken verbatim from the document or the link itself.
    """
    # 1. Named destination — the most reliable signal when present, because
    #    the PDF author wrote it deliberately: "Section_5.2" -> "Section 5.2".
    if link.target_name:
        candidate = link.target_name.replace("_", " ").replace("-", " ")
        if _REFERENCE_RE.search(candidate):
            return candidate, "target_name"

    # 2. The visible link text, when it already contains a full reference.
    if link.text and _REFERENCE_RE.search(link.text):
        return link.text, "link_text"

    # 3. The paragraph the link sits in. Anchor text is often truncated by the
    #    link rectangle, so use whatever survived to locate the paragraph and
    #    read the reference from there.
    snippet = (link.text or "").strip()[:_SNIPPET_LEN]
    if snippet:
        for paragraph in document.paragraphs:
            if paragraph.page != link.page:
                continue
            if snippet in paragraph.text and _REFERENCE_RE.search(paragraph.text):
                return paragraph.text, "paragraph"

    return link.text or "", "raw"


def _display(text: str, limit: int = 80) -> str:
    """Collapse whitespace so messages stay on one line."""
    collapsed = " ".join(text.split())
    return collapsed if len(collapsed) <= limit else collapsed[: limit - 1] + "…"


def _caption_index(document: Document) -> dict[tuple[str, str], tuple[int, str]]:
    """Every figure and table caption in the document, keyed by (type, number).

    {("Table", "5"): (page, "Table 5: Supported platforms")}

    Captions are read verbatim from paragraphs; nothing is inferred. An empty
    index means this document does not use caption lines, which is a reason to
    check nothing rather than to report everything.
    """
    captions: dict[tuple[str, str], tuple[int, str]] = {}
    for paragraph in document.paragraphs:
        first_line = paragraph.text.strip().split("\n")[0].strip()
        match = _CAPTION_RE.match(first_line)
        if not match:
            continue
        key = (match.group("kind").capitalize(), match.group("number"))
        captions.setdefault(key, (paragraph.page, first_line))
    return captions


def _prose_findings(
    document: Document,
    captions: dict[tuple[str, str], tuple[int, str]],
    already_reported: set[tuple[int, str, str]],
) -> list[Finding]:
    """Figure/Table references written as plain text, with no caption to match.

    Real manuals often write "as shown in Table 5" without a hyperlink, so the
    link check above cannot see them. If Table 5 was removed, nothing else
    would notice.

    Only runs for a reference type this document actually captions. If no
    Table captions were found, table references are not checked at all —
    absence of captions means the extraction found nothing, not that every
    reference is broken.
    """
    captioned_kinds = {kind for kind, _number in captions}
    if not captioned_kinds:
        return []

    findings: list[Finding] = []
    seen: set[tuple[str, str]] = set()

    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        # A caption line is not a reference to itself, but body text often
        # follows it in the same block, so drop only that first line.
        first_line, _, remainder = text.partition("\n")
        if _CAPTION_RE.match(first_line.strip()):
            text = remainder

        for match in _REFERENCE_RE.finditer(text):
            kind = (match.group("kind") or match.group("akind") or "").capitalize()
            number = match.group("number") or match.group("anumber")
            if kind not in _CAPTIONED_TYPES or kind not in captioned_kinds:
                continue
            if (kind, number) in captions:
                continue  # the target exists
            if (kind, number) in seen:
                continue  # report each missing target once
            if (paragraph.page, kind, number) in already_reported:
                continue  # a broken link on this page already covers it
            seen.add((kind, number))

            findings.append(
                Finding(
                    feature="broken_links",

                    page=paragraph.page,
                    message=(
                        f"Reference to {kind} {number} but the document has no "
                        f"{kind} {number}"
                    ),
                    confidence=None,
                    details={
                        "reference_type": kind,
                        "reference_text": f"{kind} {number}",
                        "evidence_source": "prose",
                        "link_text": None,
                        "reason": "no matching caption found in this document",
                        "suggested_heading": None,
                        "suggested_heading_number": None,
                        "suggested_page": None,
                        "suggestion_confidence": None,
                    },
                )
            )
    return findings


def _missing_reference_findings(document: Document) -> list[Finding]:
    """Cross-references whose text has gone, leaving a gap in the sentence.

    This is the failure mode Nokia described: their cross-references carry the
    destination title as the link text, so a broken one reads "See  to find
    information on..." with nothing where the title was. Link-annotation
    checking cannot see these — the annotation is removed along with the text.
    """
    findings: list[Finding] = []
    seen: set[tuple[int, int]] = set()

    for paragraph in document.paragraphs:
        text = " ".join(paragraph.text.split("\n"))
        for match in _REFERENCE_CUE_RE.finditer(text):
            tail = text[match.end():]
            token = _NEXT_TOKEN_RE.match(tail)
            following = token.group(1) if token else ""

            if match.group("gap").count(" ") >= 2:
                reason = "gap where the reference text should be"
            elif not following or following[0] in ".,;:)":
                reason = "sentence ends immediately after the reference cue"
            elif following.lower() in _FUNCTION_WORDS:
                reason = (
                    f"cue followed by {following!r}, with no reference "
                    f"text between them"
                )
            else:
                continue

            key = (paragraph.page, match.start())
            if key in seen:
                continue
            seen.add(key)

            cue = " ".join(match.group("cue").split())
            context = _display(_context(text, match.start()))
            findings.append(
                Finding(
                    feature="broken_links",

                    page=paragraph.page,
                    # The sentence is the finding: a reviewer needs to see the
                    # gap to judge it, and there is no number to quote.
                    message=(
                        f"Cross-reference after {cue!r} is missing its text: "
                        f"{context!r}"
                    ),
                    confidence=None,
                    details={
                        "reference_type": "Cross-reference",
                        "reference_text": context,
                        "evidence_source": "prose",
                        "link_text": None,
                        "reason": reason,
                        "suggested_heading": None,
                        "suggested_heading_number": None,
                        "suggested_page": None,
                        "suggestion_confidence": None,
                    },
                )
            )
    return findings


def _context(text: str, position: int, width: int = 70) -> str:
    """The sentence fragment around a finding, so the report shows the gap."""
    start = max(0, position - 10)
    return text[start:position + width].strip()


def _suggest_caption(
    reference: Optional[tuple[str, str]],
    captions: dict[tuple[str, str], tuple[int, str]],
) -> tuple[Optional[str], Optional[int], Optional[float]]:
    """Resolve a Figure/Table reference against the caption index."""
    if reference is None or reference[0] not in _CAPTIONED_TYPES:
        return None, None, None
    found = captions.get(reference)
    if found is None:
        return None, None, None
    page, text = found
    return text, page, _EXACT_MATCH_CONFIDENCE


def _find_reference(text: str) -> Optional[tuple[str, str]]:
    """First (type, designator) in the text, e.g. ("Section", "4.2")."""
    match = _REFERENCE_RE.search(text)
    if not match:
        return None
    kind = match.group("kind") or match.group("akind")
    number = match.group("number") or match.group("anumber")
    return kind.capitalize(), number


def _classify_reference_type(text: str) -> Optional[str]:
    reference = _find_reference(text)
    return reference[0] if reference else None


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
    reference_text: str,
    reference_type: Optional[str],
    headings: list[Heading],
) -> tuple[Optional[Heading], Optional[float]]:
    # Only heading-style references can be answered from the heading list.
    # A Figure or Table reference would otherwise match an unrelated section
    # that happens to share the same number.
    if reference_type not in _HEADING_REFERENCE_TYPES:
        return None, None

    reference = _find_reference(reference_text)
    if reference is None:
        return None, None

    target = _parse_number(reference[1])
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
