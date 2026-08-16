"""DC CAT features exposed as MCP tools.

Lets an agent decide which document check to run and call it directly.
Each tool is a thin wrapper over the existing feature service — no
detection logic lives here, and no feature file needs to change.

Run:
    python -m app.mcp_server

A feature whose dependencies are missing simply isn't registered, so this
server starts even when only some features are installed.
"""

from __future__ import annotations

import os
from typing import Any

try:  # mcp >= 2.0
    from mcp.server.mcpserver import MCPServer
except ImportError:  # mcp 1.x
    from mcp.server.fastmcp import FastMCP as MCPServer

from common.contracts import FeatureResult
from common.parser import parse

mcp = MCPServer(name="dc-cat")

MAX_FINDINGS = 100


def _run(service, path: str, options: dict | None = None) -> dict[str, Any]:
    """Parse the file and run one feature, returning a plain dict.

    Never raises: an agent should get a readable status back and be able to
    correct itself (wrong path, wrong file type) rather than see a crash.
    """
    if not os.path.isfile(path):
        return {"status": "failed", "error": f"No such file: {path}"}
    try:
        document = parse(path)
    except Exception as exc:
        return {"status": "failed", "error": f"Could not read {path}: {exc}"}
    if not service.supports(document):
        return {"status": "skipped",
                "error": f"{service.name} does not support this file type"}
    return _payload(service.process(document, options))


def _keep(findings: list, limit: int) -> list:
    """Cap the payload without letting bulk findings crowd out scarce ones.

    keyword_search appends its semantic results *after* every lexical hit,
    so a plain findings[:limit] silently drops exactly the meaning-based
    matches the tool advertises — on any document with `limit` lexical hits
    the agent would be told there were none. Semantic results are capped at
    5 by the service, so reserving room for them costs almost nothing.

    Features that don't set a match_type (broken_links, spell_check) have no
    scarce class, so this reduces to the original head-slice for them.

    The trailing [:limit] is defensive. Reserving room for the scarce class
    only stays within budget while that class is small, which today it is
    (_SEMANTIC_TOP_K is 5 against a limit of 100). Nothing enforces that
    across module boundaries, so the clamp keeps the cap honest if the
    service ever returns more semantic findings than the payload can hold.
    At the current constants it is a no-op.
    """
    if len(findings) <= limit:
        return list(findings)
    scarce = [f for f in findings if f.details.get("match_type") == "semantic"]
    bulk = [f for f in findings if f.details.get("match_type") != "semantic"]
    return (bulk[: max(0, limit - len(scarce))] + scarce)[:limit]


def _payload(result: FeatureResult, truncate: int = MAX_FINDINGS) -> dict[str, Any]:
    findings = [
        {
            "page": f.page,
            "message": f.message,
            "confidence": f.confidence,
            **f.details,
        }
        for f in _keep(result.findings, truncate)
    ]
    payload: dict[str, Any] = {
        "status": result.status,
        "finding_count": len(result.findings),
        "findings": findings,
    }
    if len(result.findings) > truncate:
        payload["truncated"] = True
    if result.error:
        payload["error"] = result.error
    if result.meta:
        payload["meta"] = result.meta
    return payload


try:
    from features.broken_links.service import BrokenLinksService

    _broken_links = BrokenLinksService()

    @mcp.tool()
    def check_broken_links(file_path: str) -> dict:
        """Check a PDF for broken internal cross-references — table-of-contents
        entries, "see Section 3.2" references, and figure or table references
        that no longer point anywhere valid.

        Returns each broken reference with its page, what it referred to, and a
        suggested correct destination when one can be found in the same
        document, with a confidence score between 0 and 1. Suggestions only
        ever name sections that genuinely exist in the document; where the
        evidence is weak no suggestion is given rather than a guess.
        """
        return _run(_broken_links, file_path)

except ImportError:  # pragma: no cover
    pass


try:
    from features.keyword_search.service import KeywordSearchService

    _keyword_search = KeywordSearchService()

    @mcp.tool()
    def search_document(file_path: str, query: str) -> dict:
        """Find where a topic is discussed in a PDF or Word document.

        Matches on meaning as well as exact wording, so searching "login" also
        finds passages about "authentication" or "identity verification". Use
        this to answer questions about what a document says, or to locate the
        section covering a topic.

        Returns ranked passages with page numbers, a text snippet, a relevance
        score, and whether each hit was an exact word match or a meaning-based
        one.
        """
        return _run(_keyword_search, file_path, {"query": query})

except ImportError:  # pragma: no cover
    pass


try:
    from features.spell_check.service import SpellCheckService

    _spell_check = SpellCheckService()

    @mcp.tool()
    def check_spelling(file_path: str) -> dict:
        """Check a PDF or Word document for spelling and word-choice mistakes,
        including ones a dictionary misses — such as "form" where "from" was
        meant.

        Each sentence is judged in context. Returns the incorrect word, the
        suggested replacement, and the sentence it appeared in. Nokia technical
        terms such as gNodeB, MOCN and X2 are never flagged.
        """
        return _run(_spell_check, file_path)

except ImportError:  # pragma: no cover
    pass


if __name__ == "__main__":
    mcp.run()
