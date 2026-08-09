"""Shared data contracts for the DC CAT prototype.

This module is the frozen inter-team agreement: everything else in the
repo depends on it, and it depends on nothing else in the repo. Feature
teams should never need to change this file — feature-specific data goes
in Finding.details instead.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional, Protocol, runtime_checkable


@dataclass
class Heading:
    text: str
    level: int
    number: Optional[str]  # e.g. "3.2"; None if the heading is unnumbered
    page: int  # 1-based


@dataclass
class Paragraph:
    text: str
    page: int  # 1-based; DOCX documents put everything on page 1
    index: int  # 0-based order of this paragraph within the document


@dataclass
class Page:
    number: int  # 1-based
    text: str


@dataclass
class LinkAnnotation:
    page: int  # 1-based page the link appears on
    text: str  # visible link text
    target_page: Optional[int] = None  # 1-based resolved target page, if any
    target_name: Optional[str] = None  # named destination, if any
    is_internal: bool = True


@dataclass
class Document:
    path: str
    format: str  # "pdf" or "docx"
    pages: list[Page] = field(default_factory=list)
    paragraphs: list[Paragraph] = field(default_factory=list)
    headings: list[Heading] = field(default_factory=list)
    links: list[LinkAnnotation] = field(default_factory=list)
    page_count: int = 0

    def full_text(self) -> str:
        return "\n".join(p.text for p in self.pages)


@dataclass
class Finding:
    feature: str
    severity: str  # "info" | "warning" | "error"
    page: Optional[int]
    message: str
    confidence: Optional[float] = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class FeatureResult:
    feature: str
    status: str  # "ok" | "failed" | "skipped"
    findings: list[Finding] = field(default_factory=list)
    error: Optional[str] = None
    meta: dict[str, Any] = field(default_factory=dict)


@runtime_checkable
class FeatureModule(Protocol):
    """Contract every feature/service class must implement."""

    name: str

    def is_available(self) -> bool:
        """Whether this feature can run at all (deps installed, etc.)."""
        ...

    def supports(self, document: Document) -> bool:
        """Whether this feature applies to the given document."""
        ...

    def process(
        self, document: Document, options: Optional[dict[str, Any]]
    ) -> FeatureResult:
        """Run the feature. Must never raise — catch everything and
        return status="failed" with the error message instead."""
        ...

    def report_columns(self) -> list[str]:
        """Extra Finding.details keys this feature wants as Excel columns."""
        ...
