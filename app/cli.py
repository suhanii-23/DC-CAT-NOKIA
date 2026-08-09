"""DC CAT command-line entry point.

Usage:
    python -m app.cli <file|folder> [--query TEXT] [--excel PATH]
"""
from __future__ import annotations

import argparse
import importlib
import os
import sys
from typing import Optional

from common import excel
from common.contracts import Document, FeatureModule, FeatureResult
from common.parser import parse

# Each entry is (module path, class name). A feature whose service.py is
# still empty (class not written yet) is skipped rather than crashing the
# whole CLI, so features can be built and run independently of each other.
_FEATURE_SOURCES = [
    ("features.broken_links.service", "BrokenLinksService"),
    ("features.keyword_search.service", "KeywordSearchService"),
    ("features.spell_check.service", "SpellCheckService"),
]


def _load_feature(module_path: str, class_name: str) -> Optional[FeatureModule]:
    try:
        module = importlib.import_module(module_path)
        feature_class = getattr(module, class_name)
    except (ImportError, AttributeError):
        return None
    return feature_class()


_loaded = [(name, _load_feature(path, name)) for path, name in _FEATURE_SOURCES]
FEATURE_MODULES: list[FeatureModule] = [f for _name, f in _loaded if f is not None]
NOT_YET_IMPLEMENTED: list[str] = [name for name, f in _loaded if f is None]

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


def _collect_files(target: str) -> list[str]:
    if os.path.isfile(target):
        return [target]
    found: list[str] = []
    for root, _dirs, names in os.walk(target):
        for name in names:
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
                found.append(os.path.join(root, name))
    return sorted(found)


def _run_document(path: str, options: dict) -> tuple[Document, list[FeatureResult]]:
    document = parse(path)
    results: list[FeatureResult] = []
    for feature in FEATURE_MODULES:
        if not feature.is_available() or not feature.supports(document):
            results.append(FeatureResult(feature=feature.name, status="skipped"))
            continue
        results.append(feature.process(document, options))
    return document, results


def _print_results(path: str, results: list[FeatureResult]) -> None:
    print(f"\n=== {path} ===")
    for result in results:
        print(f"[{result.feature}] status={result.status} findings={len(result.findings)}")
        if result.error:
            print(f"  error: {result.error}")
        for finding in result.findings:
            page = f"p{finding.page}" if finding.page is not None else "-"
            print(f"  - ({page}) {finding.message}")


def main(argv: Optional[list[str]] = None) -> int:
    arg_parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="DC CAT document quality checks"
    )
    arg_parser.add_argument("target", help="Path to a PDF/DOCX file or a folder containing them")
    arg_parser.add_argument("--query", default=None, help="Keyword to search for")
    arg_parser.add_argument("--excel", default=None, help="Path to write an Excel report to")
    args = arg_parser.parse_args(argv)

    files = _collect_files(args.target)
    if not files:
        print(f"No supported documents found at: {args.target}", file=sys.stderr)
        return 1

    for class_name in NOT_YET_IMPLEMENTED:
        print(f"(note: {class_name} not implemented yet, skipping)", file=sys.stderr)

    options = {"query": args.query}
    columns_by_feature = {feature.name: feature.report_columns() for feature in FEATURE_MODULES}

    all_results: list[FeatureResult] = []
    for path in files:
        _document, results = _run_document(path, options)
        _print_results(path, results)
        all_results.extend(results)

    if args.excel:
        excel.write_report(all_results, columns_by_feature, args.excel)
        print(f"\nExcel report written to {args.excel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
