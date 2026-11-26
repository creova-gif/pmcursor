from __future__ import annotations

import html

from pmcursor.checklists import EdgeCaseChecklist
from pmcursor.models import (
    ADRContract,
    CompletionStatus,
    DriftFinding,
    DriftReport,
    ModelContract,
    RepoMap,
    RouteContract,
    SeverityLevel,
    SpecAlignmentScore,
    TelemetryContract,
)

_STATUS_COLORS: dict[CompletionStatus, str] = {
    "DONE": "#10b981",
    "DONE_WITH_CONCERNS": "#f59e0b",
    "BLOCKED": "#ef4444",
    "NEEDS_CONTEXT": "#9494a0",
}

_SEVERITY_COLORS: dict[SeverityLevel, str] = {
    "critical": "#ef4444",
    "high": "#f59e0b",
    "medium": "#eab308",
    "low": "#9494a0",
}

_STYLES = """
:root {
  --bg: #0a0a0c;
  --pane: #121216;
  --card: #18181f;
  --border: #272730;
  --text: #f4f4f6;
  --muted: #9494a0;
  --mono: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace;
  --sans: Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
}
* { box-sizing: border-box; }
html, body {
  margin: 0;
  padding: 0;
  background: var(--bg);
  color: var(--text);
  font-family: var(--sans);
  font-size: 14px;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
.tabular { font-variant-numeric: tabular-nums; }
.mono { font-family: var(--mono); }
.canvas-header {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
  padding: 16px 24px;
  background: var(--pane);
  border-bottom: 1px solid var(--border);
}
.header-title-group {
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.header-kicker {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.08em;
  color: var(--muted);
}
.header-path {
  font-family: var(--mono);
  font-size: 13px;
  color: var(--text);
}
.header-metrics {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 12px;
}
.metric-chip {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
}
.metric-label { color: var(--muted); }
.metric-value {
  color: var(--text);
  font-weight: 600;
  font-variant-numeric: tabular-nums;
}
.status-badge {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 6px 12px;
  border-radius: 6px;
  font-size: 12px;
  font-weight: 600;
  letter-spacing: 0.03em;
  border: 1px solid var(--border);
  background: var(--card);
}
.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 9999px;
}
.split-pane {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 16px;
  padding: 16px 24px 32px;
  max-width: 1600px;
  margin: 0 auto;
}
@media (max-width: 960px) {
  .split-pane {
    grid-template-columns: 1fr;
  }
}
.pane {
  background: var(--pane);
  border: 1px solid var(--border);
  border-radius: 8px;
  padding: 20px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  min-width: 0;
}
.pane-heading {
  margin: 0;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: -0.01em;
}
.section-title {
  margin: 0 0 10px 0;
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--muted);
}
.checklist {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
  gap: 8px;
  list-style: none;
  margin: 0;
  padding: 0;
}
.checklist-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-size: 12px;
}
.check-pass { color: #10b981; font-weight: 600; }
.check-fail { color: #ef4444; font-weight: 600; }
.findings-wrap {
  overflow-x: auto;
  border: 1px solid var(--border);
  border-radius: 6px;
  background: var(--card);
}
.findings-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  text-align: left;
}
.findings-table th,
.findings-table td {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
  vertical-align: top;
}
.findings-table th {
  color: var(--muted);
  font-weight: 600;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
}
.findings-table tr:last-child td { border-bottom: none; }
.severity-pill {
  display: inline-block;
  padding: 2px 6px;
  border-radius: 4px;
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  border: 1px solid var(--border);
  background: var(--pane);
}
.prd-source {
  margin: 0;
  padding: 16px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  font-family: var(--mono);
  font-size: 12px;
  line-height: 1.6;
  color: var(--text);
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-word;
}
.search-bar {
  position: relative;
  display: flex;
  align-items: center;
}
.search-input {
  width: 100%;
  padding: 9px 36px 9px 12px;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--text);
  font-family: var(--sans);
  font-size: 13px;
  outline: none;
}
.search-input:focus { border-color: #525263; }
.search-input::placeholder { color: var(--muted); }
.search-kbd {
  position: absolute;
  right: 10px;
  padding: 2px 6px;
  background: var(--pane);
  border: 1px solid var(--border);
  border-radius: 4px;
  color: var(--muted);
  font-family: var(--mono);
  font-size: 11px;
  pointer-events: none;
}
.contract-groups {
  display: flex;
  flex-direction: column;
  gap: 18px;
}
.contract-group-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 8px;
}
.contract-count {
  font-size: 11px;
  color: var(--muted);
  font-variant-numeric: tabular-nums;
}
.contract-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.contract-card {
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  padding: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.contract-card[hidden],
.contract-group[hidden],
.empty-state[hidden] {
  display: none;
}
.contract-top {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}
.contract-name {
  font-weight: 600;
  font-size: 13px;
  color: var(--text);
}
.citation-pill {
  display: inline-block;
  padding: 2px 8px;
  background: var(--pane);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--muted);
}
.contract-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  font-size: 12px;
  color: var(--muted);
}
.field-list {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin: 0;
  padding: 0;
  list-style: none;
}
.field-pill {
  padding: 2px 7px;
  background: var(--pane);
  border: 1px solid var(--border);
  border-radius: 4px;
  font-family: var(--mono);
  font-size: 11px;
  color: var(--text);
}
.empty-state {
  padding: 24px;
  text-align: center;
  background: var(--card);
  border: 1px solid var(--border);
  border-radius: 6px;
  color: var(--muted);
  font-size: 13px;
}
"""

_SCRIPT = """
(function () {
  var input = document.getElementById("contract-search");
  var emptyState = document.getElementById("contracts-empty");
  if (!input) { return; }

  function applyFilter() {
    var query = input.value.trim().toLowerCase();
    var groups = document.querySelectorAll(".contract-group");
    var totalVisible = 0;

    for (var i = 0; i < groups.length; i++) {
      var group = groups[i];
      var cards = group.querySelectorAll(".contract-card");
      var groupVisible = 0;
      for (var j = 0; j < cards.length; j++) {
        var card = cards[j];
        var haystack = card.getAttribute("data-search") || "";
        var matches = query === "" || haystack.indexOf(query) !== -1;
        card.hidden = !matches;
        if (matches) {
          groupVisible++;
          totalVisible++;
        }
      }
      var countEl = group.querySelector(".contract-count");
      if (countEl) {
        countEl.textContent = String(groupVisible);
      }
      group.hidden = groupVisible === 0;
    }

    if (emptyState) {
      emptyState.hidden = totalVisible !== 0;
    }
  }

  input.addEventListener("input", applyFilter);
  document.addEventListener("keydown", function (event) {
    var tag = document.activeElement ? document.activeElement.tagName : "";
    var isEditable = document.activeElement && document.activeElement.isContentEditable;
    if (event.key === "/" && tag !== "INPUT" && tag !== "TEXTAREA" && tag !== "SELECT" && !isEditable) {
      event.preventDefault();
      input.focus();
      input.select();
    } else if (event.key === "Escape" && document.activeElement === input) {
      input.value = "";
      applyFilter();
      input.blur();
    }
  });
})();
"""


def _esc(value: str) -> str:
    return html.escape(value, quote=True)


def _render_header(report: DriftReport) -> str:
    status_color = _STATUS_COLORS.get(report.status, "#9494a0")
    score = report.alignment_score.overall_score
    return (
        '<header class="canvas-header">'
        '<div class="header-title-group">'
        '<span class="header-kicker">PMCursor Spec Canvas</span>'
        f'<span class="header-path">{_esc(report.prd_path)}</span>'
        "</div>"
        '<div class="header-metrics">'
        '<div class="metric-chip">'
        '<span class="metric-label">Spec Alignment</span>'
        f'<span class="metric-value tabular">{score}/100</span>'
        "</div>"
        f'<div class="status-badge" style="color: {status_color};">'
        f'<span class="status-dot" style="background: {status_color};"></span>'
        f"<span>{_esc(report.status)}</span>"
        "</div>"
        '<div class="metric-chip">'
        '<span class="metric-label">Matched Contracts</span>'
        f'<span class="metric-value tabular">{report.matched_contracts}/{report.total_spec_contracts}</span>'
        "</div>"
        '<div class="metric-chip">'
        '<span class="metric-label">Fabricated Citations</span>'
        f'<span class="metric-value tabular">{report.fabricated_citations_count}</span>'
        "</div>"
        "</div>"
        "</header>"
    )


def _render_checklist(score: SpecAlignmentScore) -> str:
    items: list[tuple[str, bool]] = [
        ("Acceptance Cards", score.has_acceptance_cards),
        ("Rollback Section", score.has_rollback_section),
        ("Out of Scope", score.has_out_of_scope_section),
        ("ADR References", score.has_adr_references),
    ]
    rows: list[str] = []
    for label, passed in items:
        badge_cls = "check-pass" if passed else "check-fail"
        badge_text = "PASS" if passed else "MISSING"
        rows.append(
            '<li class="checklist-item">'
            f"<span>{_esc(label)}</span>"
            f'<span class="{badge_cls} tabular">{badge_text}</span>'
            "</li>"
        )
    return (
        "<div>"
        '<h3 class="section-title">Workflow Readiness</h3>'
        f'<ul class="checklist">{"".join(rows)}</ul>'
        "</div>"
    )


def _render_findings_table(findings: list[DriftFinding]) -> str:
    if not findings:
        body = (
            '<tr><td colspan="5" style="color: var(--muted); text-align: center;">'
            "No drift findings detected."
            "</td></tr>"
        )
    else:
        rows: list[str] = []
        for finding in findings:
            sev_color = _SEVERITY_COLORS.get(finding.severity, "#9494a0")
            citation_html = (
                f'<span class="citation-pill">{_esc(finding.code_citation)}</span>'
                if finding.code_citation is not None
                else '<span style="color: var(--muted);">—</span>'
            )
            rows.append(
                "<tr>"
                f'<td><span class="severity-pill" style="color: {sev_color};">{_esc(finding.severity)}</span></td>'
                f'<td class="mono">{_esc(finding.category)}</td>'
                f'<td class="mono">{_esc(finding.spec_reference)}</td>'
                f"<td>{citation_html}</td>"
                f"<td>{_esc(finding.message)}</td>"
                "</tr>"
            )
        body = "".join(rows)

    return (
        "<div>"
        '<h3 class="section-title">Drift Findings</h3>'
        '<div class="findings-wrap">'
        '<table class="findings-table">'
        "<thead><tr>"
        "<th>Severity</th>"
        "<th>Category</th>"
        "<th>Spec Reference</th>"
        "<th>Code Citation</th>"
        "<th>Message</th>"
        "</tr></thead>"
        f"<tbody>{body}</tbody>"
        "</table>"
        "</div>"
        "</div>"
    )


def _render_model_card(model: ModelContract) -> str:
    field_tokens = " ".join(f"{f.name} {f.type_annotation}" for f in model.fields)
    search_blob = f"{model.name} {model.citation} {' '.join(model.base_classes)} {field_tokens}".lower()
    fields_html = "".join(
        f'<li class="field-pill">{_esc(f.name)}: {_esc(f.type_annotation)}</li>'
        for f in model.fields
    )
    bases_html = (
        f'<div class="contract-meta">Bases: {_esc(", ".join(model.base_classes))}</div>'
        if model.base_classes
        else ""
    )
    fields_block = f'<ul class="field-list">{fields_html}</ul>' if fields_html else ""
    return (
        f'<article class="contract-card" data-search="{_esc(search_blob)}">'
        '<div class="contract-top">'
        f'<span class="contract-name mono">{_esc(model.name)}</span>'
        f'<span class="citation-pill">{_esc(model.citation)}</span>'
        "</div>"
        f"{bases_html}"
        f"{fields_block}"
        "</article>"
    )


def _render_route_card(route: RouteContract) -> str:
    models_parts: list[str] = []
    if route.request_model is not None:
        models_parts.append(f"req={route.request_model}")
    if route.response_model is not None:
        models_parts.append(f"res={route.response_model}")
    models_str = " · ".join(models_parts)
    search_blob = (
        f"{route.method} {route.path} {route.function_name} {route.citation} {models_str}"
    ).lower()
    meta_html = (
        f'<div class="contract-meta mono">{_esc(route.function_name)}'
        f'{(" · " + _esc(models_str)) if models_str else ""}</div>'
    )
    return (
        f'<article class="contract-card" data-search="{_esc(search_blob)}">'
        '<div class="contract-top">'
        f'<span class="contract-name mono">{_esc(route.method)} {_esc(route.path)}</span>'
        f'<span class="citation-pill">{_esc(route.citation)}</span>'
        "</div>"
        f"{meta_html}"
        "</article>"
    )


def _render_telemetry_card(telemetry: TelemetryContract) -> str:
    props_str = " ".join(telemetry.properties)
    search_blob = (
        f"{telemetry.event_name} {telemetry.source_kind} {telemetry.citation} {props_str}"
    ).lower()
    props_html = "".join(
        f'<li class="field-pill">{_esc(prop)}</li>' for prop in telemetry.properties
    )
    props_block = f'<ul class="field-list">{props_html}</ul>' if props_html else ""
    return (
        f'<article class="contract-card" data-search="{_esc(search_blob)}">'
        '<div class="contract-top">'
        f'<span class="contract-name mono">{_esc(telemetry.event_name)}</span>'
        f'<span class="citation-pill">{_esc(telemetry.citation)}</span>'
        "</div>"
        f'<div class="contract-meta">Source: <span class="mono">{_esc(telemetry.source_kind)}</span></div>'
        f"{props_block}"
        "</article>"
    )


def _render_adr_card(adr: ADRContract) -> str:
    search_blob = f"{adr.adr_id} {adr.title} {adr.status} {adr.citation}".lower()
    return (
        f'<article class="contract-card" data-search="{_esc(search_blob)}">'
        '<div class="contract-top">'
        f'<span class="contract-name">{_esc(adr.adr_id)} · {_esc(adr.title)}</span>'
        f'<span class="citation-pill">{_esc(adr.citation)}</span>'
        "</div>"
        f'<div class="contract-meta">Status: <span>{_esc(adr.status)}</span></div>'
        "</article>"
    )


def _render_contract_group(title: str, group_id: str, cards: list[str]) -> str:
    hidden_attr = " hidden" if not cards else ""
    return (
        f'<div class="contract-group" data-group="{_esc(group_id)}"{hidden_attr}>'
        '<div class="contract-group-header">'
        f'<h3 class="section-title" style="margin: 0;">{_esc(title)}</h3>'
        f'<span class="contract-count">{len(cards)}</span>'
        "</div>"
        f'<div class="contract-list">{"".join(cards)}</div>'
        "</div>"
    )


def _render_edge_case_checklist(checklist: EdgeCaseChecklist) -> str:
    if not checklist.items:
        items_html = '<div class="empty-state">No edge-case checklist items generated.</div>'
    else:
        cards: list[str] = []
        for item in checklist.items:
            priority_badge = _esc(f"[{item.priority}]")
            cards.append(
                '<article class="contract-card">'
                '<div class="contract-top">'
                '<div style="display: flex; align-items: center; gap: 8px; flex-wrap: wrap;">'
                f'<span class="severity-pill">{priority_badge}</span>'
                f'<span class="contract-name mono">{_esc(item.contract_name)}</span>'
                "</div>"
                f'<span class="citation-pill">{_esc(item.citation)}</span>'
                "</div>"
                f'<div class="contract-meta">Category: <span class="mono">{_esc(item.category)}</span></div>'
                f'<div class="contract-meta"><strong>Scenario:</strong> {_esc(item.scenario)}</div>'
                f'<div class="contract-meta"><strong>Expected:</strong> {_esc(item.expected_behavior)}</div>'
                "</article>"
            )
        items_html = f'<div class="contract-list">{"".join(cards)}</div>'

    return (
        '<section class="edge-case-section" aria-label="QA Edge-Case Checklist">'
        '<div class="contract-group-header">'
        '<h3 class="section-title" style="margin: 0;">QA Edge-Case Checklist</h3>'
        f'<span class="contract-count tabular">Total: {checklist.total_items} · P0: {checklist.p0_count}</span>'
        "</div>"
        f"{items_html}"
        "</section>"
    )


def _render_contracts_pane(
    repo_map: RepoMap,
    checklist: EdgeCaseChecklist | None = None,
) -> str:
    model_cards = [_render_model_card(m) for m in repo_map.models]
    route_cards = [_render_route_card(r) for r in repo_map.routes]
    telemetry_cards = [_render_telemetry_card(t) for t in repo_map.telemetry]
    adr_cards = [_render_adr_card(a) for a in repo_map.adrs]

    total_cards = len(model_cards) + len(route_cards) + len(telemetry_cards) + len(adr_cards)
    empty_hidden = " hidden" if total_cards > 0 else ""

    groups_html = "".join(
        [
            _render_contract_group("Models", "models", model_cards),
            _render_contract_group("Routes", "routes", route_cards),
            _render_contract_group("Telemetry", "telemetry", telemetry_cards),
            _render_contract_group("ADRs", "adrs", adr_cards),
        ]
    )
    checklist_html = _render_edge_case_checklist(checklist) if checklist is not None else ""

    return (
        '<aside class="pane" aria-label="Codebase Contracts">'
        '<h2 class="pane-heading">Codebase Contracts</h2>'
        '<div class="search-bar">'
        '<input id="contract-search" class="search-input" type="search" '
        'placeholder="Filter models, routes, telemetry, ADRs..." '
        'aria-label="Filter codebase contracts" />'
        '<span class="search-kbd" aria-hidden="true">/</span>'
        "</div>"
        f'<div class="contract-groups">{groups_html}</div>'
        f'<div id="contracts-empty" class="empty-state"{empty_hidden}>'
        "No matching codebase contracts found."
        "</div>"
        f"{checklist_html}"
        "</aside>"
    )


def render_split_pane_canvas(
    prd_md: str,
    repo_map: RepoMap,
    report: DriftReport,
    *,
    checklist: EdgeCaseChecklist | None = None,
) -> str:
    header_html = _render_header(report)
    left_pane = (
        '<section class="pane" aria-label="Living PRD">'
        '<h2 class="pane-heading">Living PRD</h2>'
        f"{_render_checklist(report.alignment_score)}"
        f"{_render_findings_table(report.findings)}"
        "<div>"
        '<h3 class="section-title">PRD Source</h3>'
        f'<pre class="prd-source"><code>{_esc(prd_md)}</code></pre>'
        "</div>"
        "</section>"
    )
    right_pane = _render_contracts_pane(repo_map, checklist=checklist)

    return (
        "<!DOCTYPE html>"
        '<html lang="en">'
        "<head>"
        '<meta charset="utf-8" />'
        '<meta name="viewport" content="width=device-width, initial-scale=1" />'
        f"<title>PMCursor Spec Canvas — {_esc(report.prd_path)}</title>"
        f"<style>{_STYLES}</style>"
        "</head>"
        "<body>"
        f"{header_html}"
        '<main class="split-pane">'
        f"{left_pane}"
        f"{right_pane}"
        "</main>"
        f"<script>{_SCRIPT}</script>"
        "</body>"
        "</html>"
    )
