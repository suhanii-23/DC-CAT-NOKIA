"""Nokia-style cross-references: title as link text, not "Section 3.2".

Nokia sent us their own examples. Their cross-references carry the destination
TITLE ("See Modifying XYZ parameters to find information on..."), so a broken
one leaves a gap in the sentence rather than a dangling number. These are the
exact strings from that mail, working / broken / to-be-ignored.
"""

from __future__ import annotations

import pytest

from common.contracts import Document, Page, Paragraph
from features.broken_links.service import BrokenLinksService


def document_with(*paragraphs: str) -> Document:
    return Document(
        path="/tmp/nokia_style.pdf",
        format="pdf",
        pages=[Page(number=1, text="\n".join(paragraphs))],
        paragraphs=[Paragraph(text=t, page=1, index=i)
                    for i, t in enumerate(paragraphs)],
        headings=[],
        links=[],
        page_count=1,
    )


def findings_for(text: str):
    result = BrokenLinksService().process(document_with(text), None)
    return [f for f in result.findings
            if f.details.get("reference_type") == "Cross-reference"]


WORKING = [
    "See Modifying XYZ parameters to find information on how to interrogate "
    "and modify XYZ parameter values.",
    "For more information, see Configuring Signaling Connections in XYZ RNC "
    "Network.",
    "See XYZ section for further information.",
    "For instructions, refer to Activating XYZ Service Indicator in the XYZ "
    "documentation.",
    "Figure: WCDMA RAN upgrade path shows the top-down approach of the "
    "upgrade path.",
    "The software versions supporting the different releases of the XYZ "
    "elements are depicted in Table: XYZ Compatibility",
]

BROKEN = [
    "See  to find information on how to interrogate and modify XYZ parameter "
    "values.",
    "For more information, see  in XYZ RNC Network.",
    # PDF extraction often collapses the double space, so the single-space
    # form has to be caught too.
    "See to find information on how to modify XYZ parameter values.",
    "For more information, see in XYZ RNC Network.",
]

# Nokia: "Following is also an instance of a reference but, is not a cross
# reference. Such cases must be ignored."
IGNORE = [
    "See/Refer to XYZ technical support note.",
    "See the note below.",
    "For more information see the Nokia support portal.",
    # From the NSP User Guides.
    "What do I see in the Network Health Summary?",
    "The route is referred to as a Services Leaf.",
]


@pytest.mark.parametrize("text", WORKING)
def test_intact_cross_references_are_not_reported(text):
    assert findings_for(text) == []


@pytest.mark.parametrize("text", BROKEN)
def test_missing_cross_reference_text_is_reported(text):
    assert len(findings_for(text)) == 1


@pytest.mark.parametrize("text", IGNORE)
def test_references_that_are_not_cross_references_are_ignored(text):
    assert findings_for(text) == []


def test_the_report_shows_the_gap_in_context():
    """A reviewer needs to see the sentence, not just a page number."""
    finding = findings_for(BROKEN[0])[0]
    assert "to find information" in finding.details["reference_text"]
    assert finding.details["evidence_source"] == "prose"
