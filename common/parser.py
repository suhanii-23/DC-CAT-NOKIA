"""Document parsing: PDF (PyMuPDF) and DOCX (python-docx) -> common.contracts.Document.

Depends on common.contracts only.
"""
from __future__ import annotations

import os
import re
from typing import Optional

import pymupdf as fitz  # PyMuPDF

from common.contracts import Document, Heading, LinkAnnotation, Page, Paragraph

_HEADING_NUMBER_RE = re.compile(r"^\s*((?:\d+\.)*\d+)\.?\s+(.*)$")


def parse(path: str) -> Document:
    ext = os.path.splitext(path)[1].lower()
    if ext == ".pdf":
        return _parse_pdf(path)
    if ext == ".docx":
        return _parse_docx(path)
    raise ValueError(f"Unsupported document format: {ext!r}")


def _split_number_title(text: str) -> tuple[Optional[str], str]:
    match = _HEADING_NUMBER_RE.match(text)
    if match:
        return match.group(1), match.group(2).strip()
    return None, text.strip()


def _parse_pdf(path: str) -> Document:
    doc = fitz.open(path)
    try:
        pages: list[Page] = []
        paragraphs: list[Paragraph] = []
        para_index = 0

        for page_index in range(doc.page_count):
            page = doc[page_index]
            page_number = page_index + 1
            text = page.get_text("text")
            pages.append(Page(number=page_number, text=text))
            for block in text.split("\n\n"):
                block = block.strip()
                if block:
                    paragraphs.append(
                        Paragraph(text=block, page=page_number, index=para_index)
                    )
                    para_index += 1

        headings: list[Heading] = []
        for level, title, page_number in doc.get_toc(simple=True):
            number, clean_title = _split_number_title(title)
            headings.append(
                Heading(text=clean_title, level=level, number=number, page=page_number)
            )

        # Named destinations actually defined in this PDF, resolved once for the
        # whole document. Without this every named link looks unresolvable, and
        # broken-link detection flags every cross-reference in a real document:
        # a Nokia user guide with 76 working links reported 76 broken ones.
        try:
            named_destinations = doc.resolve_names() or {}
        except Exception:  # older PyMuPDF, or a malformed name tree
            named_destinations = {}

        links: list[LinkAnnotation] = []
        for page_index in range(doc.page_count):
            page = doc[page_index]
            page_number = page_index + 1
            for link in page.get_links():
                kind = link.get("kind")
                link_text = _extract_link_text(page, link.get("from"))
                if kind == fitz.LINK_GOTO:
                    target_page_index = link.get("page")
                    if target_page_index is None:
                        target_page_index = -1
                    links.append(
                        LinkAnnotation(
                            page=page_number,
                            text=link_text,
                            target_page=target_page_index + 1,
                            target_name=None,
                            is_internal=True,
                        )
                    )
                elif kind == fitz.LINK_NAMED:
                    name = link.get("nameddest") or link.get("name")
                    destination = named_destinations.get(name)
                    resolved_page = None
                    if isinstance(destination, dict):
                        page_index_value = destination.get("page")
                        if isinstance(page_index_value, int) and page_index_value >= 0:
                            resolved_page = page_index_value + 1
                    links.append(
                        LinkAnnotation(
                            page=page_number,
                            text=link_text,
                            # Resolved to a real page when the destination exists
                            # in this document; left as None when it does not,
                            # which is what makes the link broken.
                            target_page=resolved_page,
                            target_name=name,
                            is_internal=True,
                        )
                    )
                # External links (LINK_URI, LINK_LAUNCH, ...) are out of
                # scope for internal broken-link detection and are skipped.

        return Document(
            path=path,
            format="pdf",
            pages=pages,
            paragraphs=paragraphs,
            headings=headings,
            links=links,
            page_count=doc.page_count,
        )
    finally:
        doc.close()


def _extract_link_text(page: "fitz.Page", rect) -> str:
    if rect is None:
        return ""
    try:
        return page.get_textbox(rect).strip()
    except Exception:
        return ""


def _parse_docx(path: str) -> Document:
    from docx import Document as DocxDocument

    docx_doc = DocxDocument(path)
    paragraphs: list[Paragraph] = []
    headings: list[Heading] = []
    full_text_parts: list[str] = []

    for index, para in enumerate(docx_doc.paragraphs):
        text = para.text.strip()
        if not text:
            continue
        paragraphs.append(Paragraph(text=text, page=1, index=index))
        full_text_parts.append(text)
        style_name = (para.style.name if para.style is not None else "") or ""
        if style_name.lower().startswith("heading"):
            level_digits = "".join(ch for ch in style_name if ch.isdigit())
            level = int(level_digits) if level_digits else 1
            number, clean_title = _split_number_title(text)
            headings.append(Heading(text=clean_title, level=level, number=number, page=1))

    page = Page(number=1, text="\n".join(full_text_parts))
    return Document(
        path=path,
        format="docx",
        pages=[page],
        paragraphs=paragraphs,
        headings=headings,
        links=[],
        page_count=1,
    )
