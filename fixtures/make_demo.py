"""Generate fixtures/demo_manual.pdf — the document used for the live demo.

A synthetic Nokia-style technical manual, written to exercise all three
features in one file. Nothing here is real Nokia content: it is generated
from this script so it can be committed, regenerated and reviewed safely.

Deliberate faults planted in the document (keep this list in sync):

  BROKEN LINKS
    p2  TOC entry -> named destination "Section_4.2" (missing).
        Heading 4.2 exists, so this should be suggested at 0.95.
    p2  TOC entry -> named destination "Section_6.3" (missing).
        Only 6.1 and 6.2 exist, so the adjacent-sibling rule applies (0.72).
    ..  "See Figure 3" -> named destination "Figure_3" (missing).
        Classified as a Figure reference; no suggestion is expected.
    ..  "Section 9.4" -> named destination "Section_9.4" (missing).
        No section 9 exists at all; no suggestion is expected.
    p2  One TOC entry links to a real page and must NOT be flagged.

  SPELL CHECK
    "the parameter was retrieved form the OSS database"   form -> from
    "ensure that the license file is their before you begin"  their -> there

  TERMINOLOGY (must never be flagged)
    gNodeB, MOCN, RSRP, X2, airscale_rnc, SGW, eNodeB

  SEMANTIC SEARCH
    Section 4.2 discusses authentication, credentials and sign-in without
    ever using the word "login", so searching "login" should surface it
    only via the semantic pass.

Usage:
    python fixtures/make_demo.py
"""

from __future__ import annotations

import os
import textwrap

import pymupdf

OUT = os.path.join(os.path.dirname(__file__), "demo_manual.pdf")

MARGIN = 72
WIDTH = 76          # characters per line
LINE = 15           # points between lines
BODY_SIZE = 10.5
HEADING_SIZE = 15
TITLE_SIZE = 22

# (section number or None, title, [paragraphs])
SECTIONS: list[tuple[str | None, str, list[str]]] = [
    ("1", "Introduction", [
        "This manual describes the installation, configuration and routine "
        "operation of the Discovery Center management platform. It is intended "
        "for deployment engineers and operations staff who are already familiar "
        "with radio access network terminology.",
        "The platform manages a mixed estate of gNodeB and eNodeB elements and "
        "presents a single operational view across both. See Figure 3 for an "
        "overview of the deployment topology.",
        "Conventions used throughout this document are listed in Appendix A. "
        "Parameter names appear in fixed width, for example airscale_rnc, and "
        "interface names such as X2 appear unmodified.",
    ]),
    ("2", "System Architecture", [
        "The platform is built from four cooperating services: the collector, "
        "the correlation engine, the operational data store and the presentation "
        "layer. Each service may be scaled independently.",
        "Traffic between the collector and the data store is compressed and "
        "checkpointed, so a restart of either component does not lose counters "
        "that have already been acknowledged.",
    ]),
    ("2.1", "Network Elements", [
        "Supported elements include gNodeB, eNodeB and the SGW. Element records "
        "are keyed on the distinguished name reported by the element itself "
        "rather than on the address it happens to be reachable at.",
        "Where an operator shares a radio network between core operators using "
        "MOCN, each participating operator is modelled separately so that "
        "counters are attributed correctly.",
    ]),
    ("2.2", "Interfaces", [
        "Northbound interfaces expose the operational data store over a "
        "versioned interface. Southbound interfaces collect from elements on a "
        "polling cycle whose period is configurable per element class.",
        "Signal quality measurements such as RSRP are collected on the standard "
        "cycle and retained at full resolution for thirty days.",
    ]),
    ("3", "Installation", [
        "Installation is performed in two stages. The first stage provisions the "
        "operating system prerequisites; the second installs the platform "
        "packages and performs first-time initialisation.",
        "Before starting, ensure that the license file is their before you begin, "
        "since initialisation cannot complete without it.",
    ]),
    ("3.1", "Hardware Prerequisites", [
        "A minimum of eight physical cores and 32 GB of memory is required for a "
        "production installation. Laboratory installations may be run on four "
        "cores, with reduced retention.",
        "Storage must be provisioned as a single volume. Splitting the data store "
        "across volumes is not supported and will fail validation at startup.",
    ]),
    ("3.2", "Software Prerequisites", [
        "The supported operating system baselines are listed in Table 2. Applying "
        "vendor security patches is supported and expected; upgrading the kernel "
        "major version is not.",
        "The installer verifies each prerequisite before making any change, and "
        "reports every unmet condition in a single pass rather than stopping at "
        "the first failure.",
    ]),
    ("4", "Configuration", [
        "Configuration is held in a single versioned document. Changes are staged, "
        "validated and then committed, so a rejected change never leaves the "
        "system in a partially applied state.",
        "Refer to Section 9.4 for the full parameter reference.",
    ]),
    ("4.1", "Initial Setup", [
        "On first start the platform creates an empty inventory and waits for "
        "elements to be registered. Registration may be performed element by "
        "element or in bulk from a prepared file.",
        "A diagnostic report is produced at the end of initial setup. When the "
        "parameter was retrieved form the OSS database, the report records both "
        "the requested value and the value actually applied.",
    ]),
    ("4.2", "Access Control and Identity Verification", [
        "Every operator account is verified against the configured identity "
        "provider before any session is established. Credentials are never held "
        "by the platform itself; only the assertion returned by the provider is "
        "retained, and only for the lifetime of the session.",
        "Authentication failures are recorded with the originating address and "
        "the reason reported by the provider. Repeated failures from one address "
        "cause that address to be held off for an increasing interval.",
        "Where an operator requires two-factor verification, the second factor is "
        "requested by the identity provider rather than by the platform, so no "
        "additional configuration is needed here.",
    ]),
    ("5", "Operations", [
        "Routine operation is largely unattended. The tasks described in this "
        "section are the ones that require an operator decision.",
    ]),
    ("5.1", "Monitoring and Alarms", [
        "Alarms are raised against the element that reported the underlying "
        "condition, not against the collector that observed it. An alarm clears "
        "only when the reporting element confirms the condition has ended.",
        "Alarm severity is taken from the element where the element supplies one. "
        "Where it does not, severity is derived from the alarm class as shown in "
        "Table 4.",
    ]),
    ("5.2", "Performance Counters", [
        "Counters are collected on the polling cycle and aggregated at one minute, "
        "one hour and one day. Aggregates are computed from retained samples, so "
        "a late-arriving sample corrects every aggregate that contains it.",
    ]),
    ("6", "Troubleshooting", [
        "This section lists the conditions most often reported to support, and "
        "the checks that resolve them.",
    ]),
    ("6.1", "Collector Cannot Reach an Element", [
        "Confirm first that the element is reachable from the collector host and "
        "not merely from the operator workstation. The collector does not share "
        "the workstation's routing.",
        "If the element is reachable but registration still fails, the "
        "distinguished name reported by the element has probably changed.",
    ]),
    ("6.2", "OSS Database Errors", [
        "Errors reported by the operational data store are recorded with the "
        "originating query and the connection identifier. Both are needed when "
        "raising a support case.",
        "A sustained rise in rejected writes usually indicates that retention has "
        "not been applied, rather than a fault in the data store itself.",
    ]),
    (None, "Appendix A: Glossary", [
        "gNodeB — 5G base station. eNodeB — LTE base station. MOCN — Multi "
        "Operator Core Network. RSRP — Reference Signal Received Power. SGW — "
        "Serving Gateway. X2 — interface between base stations.",
        "airscale_rnc — the radio network controller parameter group.",
    ]),
]

# Table-of-contents rows: (label, link kind, target)
#   ("page", n)  -> a working link to page index n
#   ("named", s) -> a link to named destination s (broken when s does not exist)
TOC_LINKS = [
    ("1. Introduction", "page", 2),                    # valid: must NOT be flagged
    ("4.2 Access Control and Identity Verification", "named", "Section_4.2"),
    ("6.3 Retention Failures", "named", "Section_6.3"),
]


def _write_paragraph(page, text: str, y: float) -> float:
    for line in textwrap.wrap(text, WIDTH):
        page.insert_text((MARGIN, y), line, fontsize=BODY_SIZE)
        y += LINE
    return y + LINE * 0.6


def build() -> str:
    doc = pymupdf.open()

    # --- title page
    title = doc.new_page()
    title.insert_text((MARGIN, 200), "Discovery Center", fontsize=TITLE_SIZE)
    title.insert_text((MARGIN, 232), "Installation and Operations Manual",
                      fontsize=TITLE_SIZE)
    title.insert_text((MARGIN, 280), "Release 24.2  |  Document DC-OPS-24.2",
                      fontsize=BODY_SIZE)
    title.insert_text((MARGIN, 300), "Synthetic demonstration document — not real "
                                     "product documentation.", fontsize=BODY_SIZE)

    # --- table of contents (links added later, once pages exist)
    doc.new_page()

    # --- body, one section per page (long sections spill onto a second page)
    toc_entries: list[list] = []
    for number, heading_title, paragraphs in SECTIONS:
        page = doc.new_page()
        page_number = doc.page_count            # 1-based
        label = f"{number} {heading_title}" if number else heading_title
        page.insert_text((MARGIN, 96), label, fontsize=HEADING_SIZE)

        level = 1 if (number is None or "." not in number) else 2
        toc_entries.append([level, label, page_number])

        y = 140.0
        for paragraph in paragraphs:
            if y > 700:
                page = doc.new_page()
                y = 110.0
            y = _write_paragraph(page, paragraph, y)

    doc.set_toc(toc_entries)

    # Pages must be re-fetched after set_toc: earlier handles are invalidated.
    contents = doc[1]
    contents.insert_text((MARGIN, 96), "Table of Contents", fontsize=HEADING_SIZE)

    y = 140.0
    for label, kind, target in TOC_LINKS:
        contents.insert_text((MARGIN, y), label, fontsize=BODY_SIZE)
        rect = pymupdf.Rect(MARGIN, y - 11, MARGIN + 380, y + 4)
        if kind == "page":
            contents.insert_link({"kind": pymupdf.LINK_GOTO, "from": rect,
                                  "page": target})
        else:
            contents.insert_link({"kind": pymupdf.LINK_NAMED, "from": rect,
                                  "name": target})
        y += 22

    # In-text references that no longer resolve.
    _link_phrase(doc, "See Figure 3", "Figure_3")
    _link_phrase(doc, "Refer to Section 9.4", "Section_9.4")

    doc.save(OUT)
    pages = doc.page_count
    doc.close()
    print(f"Wrote {OUT} ({pages} pages)")
    return OUT


def _link_phrase(doc, phrase: str, destination: str) -> None:
    """Attach a broken named-destination link to the first occurrence of a phrase."""
    for index in range(doc.page_count):
        page = doc[index]
        hits = page.search_for(phrase)
        if hits:
            page.insert_link({"kind": pymupdf.LINK_NAMED, "from": hits[0],
                              "name": destination})
            return


if __name__ == "__main__":
    build()
