"use client";

import type {
  DriftReport,
  EdgeCaseChecklist,
  SeverityLevel,
} from "@/lib/types";

const SEVERITY_ORDER: SeverityLevel[] = ["critical", "high", "medium", "low"];

function severityRank(severity: SeverityLevel): number {
  return SEVERITY_ORDER.indexOf(severity);
}

export default function SpecPane({
  prdMarkdown,
  onPrdChange,
  report,
  checklist,
}: {
  prdMarkdown: string;
  onPrdChange: (value: string) => void;
  report: DriftReport | null;
  checklist: EdgeCaseChecklist | null;
}) {
  const findings = report
    ? [...report.findings].sort(
        (a, b) => severityRank(a.severity) - severityRank(b.severity),
      )
    : [];

  return (
    <section className="pane pane-left" aria-labelledby="prd-pane-heading">
      <h2 id="prd-pane-heading" className="pane-heading">
        Living PRD
      </h2>

      {report ? (
        <div className="score-strip" aria-label="Alignment score details">
          <span>overall {report.alignment_score.overall_score}</span>
          <span>deterministic {report.alignment_score.deterministic_score}</span>
          <span>workflow {report.alignment_score.workflow_score}</span>
          <span>{report.total_citations_checked} citations checked</span>
        </div>
      ) : null}

      {findings.length > 0 ? (
        <table className="findings-table">
          <caption className="sr-only">Drift findings</caption>
          <thead>
            <tr>
              <th scope="col">Severity</th>
              <th scope="col">Category</th>
              <th scope="col">Spec reference</th>
              <th scope="col">Citation</th>
              <th scope="col">Finding</th>
            </tr>
          </thead>
          <tbody>
            {findings.map((finding, index) => (
              <tr key={`${finding.spec_reference}-${index}`}>
                <td>
                  <span className={`badge sev-${finding.severity}`}>
                    {finding.severity}
                  </span>
                </td>
                <td>
                  <code>{finding.category}</code>
                </td>
                <td className="cell-wrap">{finding.spec_reference}</td>
                <td>
                  {finding.code_citation ? (
                    <code>{finding.code_citation}</code>
                  ) : (
                    "—"
                  )}
                </td>
                <td className="cell-wrap">
                  {finding.message}
                  <span className="remediation">{finding.remediation}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      ) : report ? (
        <p className="empty-note">No drift findings — spec and code agree.</p>
      ) : null}

      {checklist ? (
        <details className="checklist-block">
          <summary>
            Edge-case checklist — {checklist.total_items} items (
            {checklist.p0_count} P0)
          </summary>
          <ol className="checklist-items">
            {checklist.items.map((item) => (
              <li key={`${item.contract_name}-${item.citation}`}>
                <span className={`badge pri-${item.priority.toLowerCase()}`}>
                  {item.priority}
                </span>{" "}
                <strong>{item.contract_name}</strong>{" "}
                <code>{item.citation}</code>
                <p>{item.scenario}</p>
                <p className="remediation">Expected: {item.expected_behavior}</p>
              </li>
            ))}
          </ol>
        </details>
      ) : null}

      <div>
        <h3 className="section-title">
          <label htmlFor="prd-source">PRD source</label>
        </h3>
        <textarea
          id="prd-source"
          className="prd-source"
          value={prdMarkdown}
          onChange={(event) => onPrdChange(event.target.value)}
          spellCheck={false}
          rows={22}
        />
      </div>
    </section>
  );
}
