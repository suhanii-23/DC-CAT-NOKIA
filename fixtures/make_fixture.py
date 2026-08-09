"""Generate fixtures/sample.pdf.

Produces a small PDF with:
  - a TOC with numbered headings (1, 2, 2.1, 3, 3.1, 4)
  - one valid internal link ("See Section 2.1...")
  - two broken named-destination links ("See Section 3.2...", "See Figure 7...")
  - a deliberate real-word spelling error ("retrieved form the OSS database")

Run with: python fixtures/make_fixture.py
"""
from __future__ import annotations

import os

import pymupdf as fitz  # PyMuPDF

OUTPUT_PATH = os.path.join(os.path.dirname(__file__), "sample.pdf")


def _add_page(doc: fitz.Document, lines: list[str]) -> fitz.Page:
    page = doc.new_page()
    y = 72
    for line in lines:
        if line:
            page.insert_text((72, y), line, fontsize=12)
        y += 20
    return page


def build() -> None:
    doc = fitz.open()

    _add_page(
        doc,
        [
            "1 Introduction",
            "",
            "This document describes the OSS authentication and configuration",
            "workflow used during the DC CAT prototype evaluation.",
        ],
    )

    _add_page(
        doc,
        [
            "2 Configuration",
            "",
            "2.1 Network Setup",
            "",
            "The parameter was retrieved form the OSS database.",
            "See Section 2.1 for details on authentication parameters.",
        ],
    )

    _add_page(
        doc,
        [
            "3 Troubleshooting",
            "",
            "3.1 OSS Database Errors",
            "",
            "See Section 3.2 for retry logic when authentication fails.",
        ],
    )

    _add_page(
        doc,
        [
            "4 Appendix A",
            "",
            "See Figure 7 for the topology diagram.",
        ],
    )

    doc.set_toc(
        [
            [1, "1 Introduction", 1],
            [1, "2 Configuration", 2],
            [2, "2.1 Network Setup", 2],
            [1, "3 Troubleshooting", 3],
            [2, "3.1 OSS Database Errors", 3],
            [1, "4 Appendix A", 4],
        ]
    )

    # set_toc() invalidates previously fetched Page objects, so re-fetch
    # fresh handles before inserting links.
    page2 = doc[1]
    page3 = doc[2]
    page4 = doc[3]

    # Valid internal link: correctly points back to page 2 (where 2.1 lives).
    rect = page2.search_for("See Section 2.1 for details on authentication parameters.")[0]
    page2.insert_link(
        {"kind": fitz.LINK_GOTO, "from": rect, "page": 1, "to": fitz.Point(72, 72)}
    )

    # Broken named-destination link #1: "section3_2" is never registered.
    rect = page3.search_for("See Section 3.2 for retry logic when authentication fails.")[0]
    page3.insert_link({"kind": fitz.LINK_NAMED, "from": rect, "name": "section3_2"})

    # Broken named-destination link #2: "figure7" is never registered, and
    # there is no Figure heading anywhere in the document.
    rect = page4.search_for("See Figure 7 for the topology diagram.")[0]
    page4.insert_link({"kind": fitz.LINK_NAMED, "from": rect, "name": "figure7"})

    doc.save(OUTPUT_PATH)
    doc.close()
    print(f"Wrote {OUTPUT_PATH}")


if __name__ == "__main__":
    build()
