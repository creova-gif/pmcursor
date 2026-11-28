from __future__ import annotations

from typing import Any

from pmcursor.models import DriftReport, SeverityLevel

SARIF_SCHEMA_URL = (
    "https://raw.githubusercontent.com/oasis-tcs/sarif-spec/master/"
    "Schemata/sarif-schema-2.1.0.json"
)
SARIF_VERSION = "2.1.0"
TOOL_NAME = "PMCursor"
TOOL_INFORMATION_URI = "https://github.com/creova-gif/pmcursor"
TOOL_VERSION = "0.3.0"

_SEVERITY_TO_SARIF_LEVEL: dict[SeverityLevel, str] = {
    "critical": "error",
    "high": "error",
    "medium": "warning",
    "low": "note",
}


def _parse_location(raw_location: str) -> tuple[str, int | None]:
    """Split a ``path:line`` citation into ``(uri, startLine)`` when valid."""
    if ":" in raw_location:
        path_part, line_part = raw_location.rsplit(":", 1)
        if path_part and line_part.isdigit():
            line_num = int(line_part)
            if line_num > 0:
                return path_part, line_num
    return raw_location, None


def drift_report_to_sarif(report: DriftReport) -> dict[str, Any]:
    """Convert a ``DriftReport`` into a SARIF 2.1.0 JSON-serializable dict."""
    categories = sorted({finding.category for finding in report.findings})
    rules: list[dict[str, Any]] = [
        {
            "id": category,
            "name": category,
            "shortDescription": {"text": f"PMCursor drift check: {category}"},
        }
        for category in categories
    ]

    results: list[dict[str, Any]] = []
    for finding in report.findings:
        raw_loc = finding.code_citation or report.prd_path
        uri, start_line = _parse_location(raw_loc)
        physical_location: dict[str, Any] = {
            "artifactLocation": {"uri": uri},
        }
        if start_line is not None:
            physical_location["region"] = {"startLine": start_line}

        results.append(
            {
                "ruleId": finding.category,
                "level": _SEVERITY_TO_SARIF_LEVEL[finding.severity],
                "message": {"text": finding.message},
                "locations": [
                    {
                        "physicalLocation": physical_location,
                    }
                ],
                "properties": {
                    "specReference": finding.spec_reference,
                    "remediation": finding.remediation,
                },
            }
        )

    return {
        "$schema": SARIF_SCHEMA_URL,
        "version": SARIF_VERSION,
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": TOOL_NAME,
                        "informationUri": TOOL_INFORMATION_URI,
                        "version": TOOL_VERSION,
                        "rules": rules,
                    }
                },
                "results": results,
            }
        ],
    }
