"""Command-line entry point for multi-document keyword search.

Lives inside this feature's own folder, not in app/: the repo rule is that
a feature team edits nothing outside features/<its-name>/, and app/cli.py
belongs to everyone. It is also a separate command on purpose — app/cli.py
runs the per-document feature suite, and folding a multi-document feature
into its `--features all` run would change what an existing command
prints. This one does a single job: one keyword, many documents, every
occurrence, one report.

Usage:
    python -m features.multi_doc_keyword_search.cli <file|folder> [more...]
                                   --keyword TEXT [--excel PATH | --no-excel]

Examples:
    python -m features.multi_doc_keyword_search.cli document1.pdf document2.pdf \
        document3.pdf --keyword embedded --excel report.xlsx
    python -m features.multi_doc_keyword_search.cli docs/ --keyword MOCN

Excel output: a search that covered two or more documents writes an .xlsx
report automatically, named after the keyword. `--excel PATH` picks the
path (and forces a report even for a single document); `--no-excel`
suppresses it entirely. The report has one sheet with the columns
Document, Page, Keyword, Match and Context — see report.py.

Terminal output is a short summary: matches per document and in total.
When no report is written, every match is also listed, since the
terminal is then the only place to see them.
"""

from __future__ import annotations

import argparse
import re
import sys
from typing import Optional

from features.multi_doc_keyword_search.report import write_xlsx
from features.multi_doc_keyword_search.service import (
    MultiDocKeywordSearchService,
    MultiDocSearchResult,
)

# A search covering at least this many documents writes a report without
# being asked.
_AUTO_EXCEL_MIN_DOCUMENTS = 2

_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9]+")


def _default_report_path(keyword: str) -> str:
    """Report filename derived from the keyword, for the automatic case.

    Written into the current directory, mirroring how `--excel report.xlsx`
    is used elsewhere in the repo. The keyword is slugified because it is
    user input and may contain path separators or characters the
    filesystem rejects.
    """
    slug = _UNSAFE_FILENAME_CHARS.sub("_", keyword).strip("_").lower()[:40]
    return f"keyword_matches_{slug or 'search'}.xlsx"


def _plural(count: int, word: str) -> str:
    return f"{count} {word}" if count == 1 else f"{count} {word}es"


def _print_matches(result: MultiDocSearchResult) -> None:
    """Every match, grouped by document and page."""
    names = result.document_names()
    for document in result.documents:
        if not document.match_count:
            continue
        print(f"\n{names[document.path]}  ({_plural(document.match_count, 'match')})")
        current_page: Optional[int] = None
        for finding in document.findings:
            if finding.page != current_page:
                current_page = finding.page
                print(f"  Page {current_page}")
            print(f"    {finding.details['context']}")
    print()


def _print_summary(result: MultiDocSearchResult, report_path: Optional[str]) -> None:
    names = result.document_names()
    print("Multi-document keyword search completed.")
    print()
    print(f"Keyword: {result.keyword}")
    print(f"Documents searched: {result.documents_searched}")
    for document in result.documents:
        line = f"  {names[document.path]}: {_plural(document.match_count, 'match')}"
        if document.looks_scanned:
            line += (
                "  (almost no extractable text: probably scanned images, "
                "so this document could not really be searched)"
            )
        print(line)
    if result.errors:
        print(f"Skipped: {len(result.errors)} (reasons below)")
    print(f"Total matches: {result.total_matches}")
    if report_path:
        print(f"Output: {report_path}")
    if not result.total_matches:
        print(f"No matches found for keyword: {result.keyword}")

    for problem in result.errors:
        print(f"(skipped {problem['document']}: {problem['error']})", file=sys.stderr)


def main(argv: Optional[list[str]] = None) -> int:
    arg_parser = argparse.ArgumentParser(
        prog="python -m features.multi_doc_keyword_search.cli",
        description=(
            "Search one exact keyword across many PDF/DOCX documents and "
            "write one Excel report. Literal, case-insensitive, whole-word "
            "— never semantic."
        ),
    )
    arg_parser.add_argument(
        "targets", nargs="+", help="PDF/DOCX files and/or folders to search"
    )
    arg_parser.add_argument(
        "--keyword", required=True, help="The exact keyword to search for"
    )
    excel_group = arg_parser.add_mutually_exclusive_group()
    excel_group.add_argument(
        "--excel",
        default=None,
        help="Path to write the Excel report to (forces a report even for a "
        "single document)",
    )
    excel_group.add_argument(
        "--no-excel",
        action="store_true",
        help="Never write an Excel report, not even for multiple documents",
    )
    args = arg_parser.parse_args(argv)

    service = MultiDocKeywordSearchService()
    result = service.search(args.targets, args.keyword)

    if result.status == "failed":
        print(f"Search failed: {result.error}", file=sys.stderr)
        return 2

    report_path = _report_path(args, result)
    if report_path:
        try:
            write_xlsx(result, report_path)
        except OSError as exc:
            # Typically the file is open in Excel. The search itself worked,
            # so show the matches rather than losing them.
            print(f"Could not write the Excel report: {exc}", file=sys.stderr)
            _print_matches(result)
            _print_summary(result, None)
            return 1
    else:
        _print_matches(result)

    _print_summary(result, report_path)
    return 0


def _report_path(args: argparse.Namespace, result: MultiDocSearchResult) -> Optional[str]:
    """Where to write the Excel report, or None to write none.

    An explicit --excel always wins; --no-excel always suppresses. Left to
    itself, a search that covered several documents gets a report and a
    single-document search does not.
    """
    if args.no_excel:
        return None
    if args.excel:
        return args.excel
    if result.documents_searched >= _AUTO_EXCEL_MIN_DOCUMENTS:
        return _default_report_path(result.keyword)
    return None


if __name__ == "__main__":
    raise SystemExit(main())
