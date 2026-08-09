"""Excel report writer: one Summary sheet plus one sheet per feature.

Depends on common.contracts only.
"""
from __future__ import annotations

from typing import Iterable

from openpyxl import Workbook

from common.contracts import FeatureResult

_BASE_COLUMNS = ["page", "severity", "message", "confidence"]


def write_report(
    results: Iterable[FeatureResult],
    columns_by_feature: dict[str, list[str]],
    out_path: str,
) -> None:
    results = list(results)

    workbook = Workbook()
    summary_sheet = workbook.active
    summary_sheet.title = "Summary"
    summary_sheet.append(["Feature", "Status", "Findings", "Error"])

    used_titles: set[str] = {"Summary"}
    for result in results:
        summary_sheet.append(
            [result.feature, result.status, len(result.findings), result.error or ""]
        )

        title = _unique_sheet_title(result.feature, used_titles)
        used_titles.add(title)
        sheet = workbook.create_sheet(title=title)

        extra_columns = columns_by_feature.get(result.feature, [])
        sheet.append(_BASE_COLUMNS + extra_columns)
        for finding in result.findings:
            row = [finding.page, finding.severity, finding.message, finding.confidence]
            row += [_to_cell_value(finding.details.get(col)) for col in extra_columns]
            sheet.append(row)

    workbook.save(out_path)


def _to_cell_value(value):
    if isinstance(value, (list, tuple, set)):
        return ", ".join(str(v) for v in value)
    if isinstance(value, dict):
        return str(value)
    return value


def _unique_sheet_title(name: str, used: set[str]) -> str:
    title = name[:31]
    suffix = 2
    while title in used:
        title = f"{name[:28]}~{suffix}"
        suffix += 1
    return title
