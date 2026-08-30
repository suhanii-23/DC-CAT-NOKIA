"""DC CAT command-line entry point.

Usage:
    python -m app.cli <file|folder> [--features NAMES] [--query TEXT] [--excel PATH]

Examples:
    python -m app.cli fixtures/sample.pdf --excel report.xlsx
    python -m app.cli fixtures/sample.pdf --features broken_links --excel bl.xlsx
    python -m app.cli docs/ --features keyword_search --query authentication
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

# The LangGraph agent orchestrates the feature services. It is optional: if
# langgraph is not installed the CLI falls back to calling the services
# directly, so a missing orchestration dependency never takes down features
# that do not need it — broken_links, for one, has no dependencies at all.
try:
    from app.agent.graph import agent_graph
except ImportError:  # pragma: no cover - exercised only without langgraph
    agent_graph = None

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

# Every feature name the project knows about, implemented or not. Derived from
# the folder name in the module path, so --features can tell "you typed a name
# that doesn't exist" apart from "that feature isn't written yet".
ALL_FEATURE_NAMES: list[str] = [path.split(".")[1] for path, _name in _FEATURE_SOURCES]

SUPPORTED_EXTENSIONS = {".pdf", ".docx"}

# Detail keys worth surfacing on the terminal, in the order features tend to
# fill them. Everything else stays in the Excel report.
_SUGGESTION_KEYS = ("suggested_heading", "suggestion", "suggested_correction")


def _collect_files(target: str) -> list[str]:
    if os.path.isfile(target):
        return [target]
    found: list[str] = []
    for root, _dirs, names in os.walk(target):
        for name in names:
            if os.path.splitext(name)[1].lower() in SUPPORTED_EXTENSIONS:
                found.append(os.path.join(root, name))
    return sorted(found)


def _select_features(
    requested: str, arg_parser: argparse.ArgumentParser
) -> list[FeatureModule]:
    """Turn the --features value into the list of feature objects to run.

    Exits via arg_parser.error() on an unknown name; prints a note and carries
    on for a known-but-unimplemented one.
    """
    if requested == "all":
        for class_name in NOT_YET_IMPLEMENTED:
            print(f"(note: {class_name} not implemented yet, skipping)", file=sys.stderr)
        return list(FEATURE_MODULES)

    wanted = [name.strip() for name in requested.split(",") if name.strip()]
    if not wanted:
        arg_parser.error("--features was empty; omit it to run all features")

    unknown = [name for name in wanted if name not in ALL_FEATURE_NAMES]
    if unknown:
        arg_parser.error(
            f"unknown feature(s): {', '.join(unknown)}. "
            f"Choose from: {', '.join(ALL_FEATURE_NAMES)}"
        )

    selected = [f for f in FEATURE_MODULES if f.name in wanted]

    found_names = {f.name for f in selected}
    for name in wanted:
        if name not in found_names:
            print(f"(note: {name} is not implemented yet, skipping)", file=sys.stderr)

    return selected


def _run_document(
    path: str, options: dict, features: list[FeatureModule]
) -> tuple[Document, list[FeatureResult]]:
    document = parse(path)

    if agent_graph is None:
        return document, _run_features_directly(document, options, features)

    agent_result = agent_graph.invoke(
        {
            "document": document,
            "options": options,
            "selected_features": [feature.name for feature in features],
        }
    )

    return document, agent_result["results"]


def _run_features_directly(
    document: Document, options: dict, features: list[FeatureModule]
) -> list[FeatureResult]:
    """Fallback used when the agent graph is unavailable.

    Produces the same results in the same order as the graph, so output does
    not depend on whether langgraph happens to be installed.
    """
    results: list[FeatureResult] = []
    for feature in features:
        if not feature.is_available() or not feature.supports(document):
            results.append(FeatureResult(feature=feature.name, status="skipped"))
            continue
        results.append(feature.process(document, options))
    return results


def _finding_detail(finding) -> str:
    """One-line follow-up under a finding: the suggested fix and its confidence.

    Feature-agnostic: each feature stores its suggestion under its own key in
    Finding.details, so the first matching key wins. An empty string means
    there is nothing extra worth printing.
    """
    details = finding.details or {}

    suggestion = None
    for key in _SUGGESTION_KEYS:
        value = details.get(key)
        if value:
            suggestion = value
            break

    parts = []
    if suggestion:
        page = details.get("suggested_page")
        parts.append(f"suggested: {suggestion}" + (f" (p{page})" if page else ""))
    elif details.get("reference_type"):
        # A reference we understood but could not resolve — saying so is the
        # point, since refusing to guess is the designed behaviour.
        parts.append("no confident suggestion")

    confidence = finding.confidence
    if confidence is None:
        confidence = details.get("suggestion_confidence")
    if confidence is not None:
        parts.append(f"confidence {confidence:.2f}")

    return "  |  ".join(parts)


def _print_results(path: str, results: list[FeatureResult]) -> None:
    print(f"\n=== {path} ===")
    for result in results:
        print(f"[{result.feature}] status={result.status} findings={len(result.findings)}")
        if result.error:
            print(f"  error: {result.error}")
        for finding in result.findings:
            page = f"p{finding.page}" if finding.page is not None else "-"
            print(f"  - ({page}) {finding.message}")
            detail = _finding_detail(finding)
            if detail:
                print(f"        {detail}")


def main(argv: Optional[list[str]] = None) -> int:
    arg_parser = argparse.ArgumentParser(
        prog="python -m app.cli", description="DC CAT document quality checks"
    )
    arg_parser.add_argument("target", help="Path to a PDF/DOCX file or a folder containing them")
    arg_parser.add_argument(
        "--features",
        default="all",
        help="Comma-separated features to run: " + ", ".join(ALL_FEATURE_NAMES)
        + " (default: all)",
    )
    arg_parser.add_argument("--query", default=None, help="Keyword to search for")
    arg_parser.add_argument("--excel", default=None, help="Path to write an Excel report to")
    args = arg_parser.parse_args(argv)

    files = _collect_files(args.target)
    if not files:
        print(f"No supported documents found at: {args.target}", file=sys.stderr)
        return 1

    selected = _select_features(args.features, arg_parser)
    if not selected:
        print("None of the requested features are implemented yet.", file=sys.stderr)
        return 1

    options = {"query": args.query}
    columns_by_feature = {feature.name: feature.report_columns() for feature in selected}

    all_results: list[FeatureResult] = []
    for path in files:
        _document, results = _run_document(path, options, selected)
        _print_results(path, results)
        all_results.extend(results)

    if args.excel:
        excel.write_report(all_results, columns_by_feature, args.excel)
        print(f"\nExcel report written to {args.excel}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
