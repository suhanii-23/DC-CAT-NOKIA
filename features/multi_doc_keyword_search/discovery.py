"""Document discovery for multi-document keyword search.

Turns whatever the caller passed — a file, a folder, or a mixed list of
both — into a de-duplicated, sorted list of document paths to search,
plus the targets that had to be skipped and why.

Skipped targets are *returned*, not raised: one bad path must not stop a
multi-document search from reporting the documents that were readable.
"""
from __future__ import annotations

import os
from typing import Iterable, NamedTuple, Union

# Same set app/cli.py walks folders with. Duplicated rather than imported
# so the features layer keeps depending only on common/ — features are
# not supposed to import from app/.
SUPPORTED_EXTENSIONS = {".pdf", ".docx"}


class Discovery(NamedTuple):
    paths: list[str]  # documents to search, sorted, de-duplicated
    skipped: list[tuple[str, str]]  # (target, reason)


def discover(targets: Union[str, Iterable[str]]) -> Discovery:
    """Expand targets into document paths.

    A folder is walked recursively for supported extensions. A file named
    explicitly is taken as-is if its extension is supported, and skipped
    with a reason otherwise. A path that does not exist is skipped with a
    reason.
    """
    if isinstance(targets, str):
        targets = [targets]

    found: list[str] = []
    skipped: list[tuple[str, str]] = []

    for target in targets:
        if not isinstance(target, str) or not target.strip():
            skipped.append((str(target), "not a usable path"))
            continue
        if os.path.isdir(target):
            found.extend(_walk(target))
            continue
        if not os.path.exists(target):
            skipped.append((target, "no such file or folder"))
            continue
        if not _is_supported(target):
            skipped.append((target, "unsupported file type (expected .pdf or .docx)"))
            continue
        found.append(target)

    # Normalise so the same document reached through two targets (a file
    # named directly and the folder containing it) is searched once.
    unique = sorted({os.path.normpath(path) for path in found})
    return Discovery(paths=unique, skipped=skipped)


def _walk(folder: str) -> list[str]:
    out: list[str] = []
    for root, _dirs, names in os.walk(folder):
        for name in names:
            if _is_supported(name):
                out.append(os.path.join(root, name))
    return out


def _is_supported(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in SUPPORTED_EXTENSIONS
