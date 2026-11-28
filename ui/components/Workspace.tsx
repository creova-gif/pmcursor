"use client";

import { useCallback, useState } from "react";
import {
  generateChecklist,
  indexRepo,
  runDriftAudit,
} from "@/lib/api";
import type {
  DriftReport,
  EdgeCaseChecklist,
  RepoMap,
} from "@/lib/types";
import ContractsPane from "@/components/ContractsPane";
import SpecPane from "@/components/SpecPane";

const DEFAULT_PRD = `# Order Service PRD

## Data Model
- \`Order\` in \`app/models.py\` with fields \`order_id: str\`, \`total_cents: int\`

## API Surface
- \`GET /orders/{order_id}\` returns an \`Order\`
`;

export default function Workspace() {
  const [prdMarkdown, setPrdMarkdown] = useState(DEFAULT_PRD);
  const [repoRoot, setRepoRoot] = useState(".");
  const [prdPath, setPrdPath] = useState("PROJECT_SPEC.md");
  const [report, setReport] = useState<DriftReport | null>(null);
  const [repoMap, setRepoMap] = useState<RepoMap | null>(null);
  const [checklist, setChecklist] = useState<EdgeCaseChecklist | null>(null);
  const [busy, setBusy] = useState<"audit" | "checklist" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const runAudit = useCallback(async () => {
    setBusy("audit");
    setError(null);
    try {
      const [nextReport, nextMap] = await Promise.all([
        runDriftAudit({
          prd_markdown: prdMarkdown,
          repo_root: repoRoot,
          prd_path: prdPath,
        }),
        indexRepo(repoRoot),
      ]);
      setReport(nextReport);
      setRepoMap(nextMap);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  }, [prdMarkdown, repoRoot, prdPath]);

  const runChecklist = useCallback(async () => {
    setBusy("checklist");
    setError(null);
    try {
      const next = await generateChecklist({
        prd_markdown: prdMarkdown,
        repo_root: repoRoot,
      });
      setChecklist(next);
    } catch (exc) {
      setError(exc instanceof Error ? exc.message : String(exc));
    } finally {
      setBusy(null);
    }
  }, [prdMarkdown, repoRoot]);

  return (
    <div className="workspace-shell">
      <a className="skip-link" href="#main-workspace">
        Skip to workspace
      </a>
      <header className="canvas-header" role="banner">
        <div className="header-titles">
          <h1>PMCursor Spec Canvas</h1>
          {report ? (
            <p className="header-meta">
              <span className={`status-chip status-${report.status.toLowerCase()}`}>
                {report.status}
              </span>
              <span>
                alignment {report.alignment_score.overall_score}/100
              </span>
              <span>
                {report.matched_contracts}/{report.total_spec_contracts} contracts
              </span>
              {report.fabricated_citations_count > 0 ? (
                <span className="status-chip status-blocked">
                  {report.fabricated_citations_count} fabricated citations
                </span>
              ) : null}
            </p>
          ) : (
            <p className="header-meta">Run an audit to populate the canvas.</p>
          )}
        </div>
        <form
          className="controls"
          onSubmit={(event) => {
            event.preventDefault();
            void runAudit();
          }}
        >
          <label>
            Repo root
            <input
              type="text"
              value={repoRoot}
              onChange={(event) => setRepoRoot(event.target.value)}
              placeholder="."
            />
          </label>
          <label>
            PRD path
            <input
              type="text"
              value={prdPath}
              onChange={(event) => setPrdPath(event.target.value)}
              placeholder="PROJECT_SPEC.md"
            />
          </label>
          <button type="submit" disabled={busy !== null}>
            {busy === "audit" ? "Auditing…" : "Run drift audit"}
          </button>
          <button
            type="button"
            disabled={busy !== null}
            onClick={() => void runChecklist()}
          >
            {busy === "checklist" ? "Generating…" : "Edge-case checklist"}
          </button>
        </form>
      </header>
      {error ? (
        <p className="error-banner" role="alert">
          {error}
        </p>
      ) : null}
      <main id="main-workspace" className="split-workspace">
        <SpecPane
          prdMarkdown={prdMarkdown}
          onPrdChange={setPrdMarkdown}
          report={report}
          checklist={checklist}
        />
        <ContractsPane repoMap={repoMap} />
      </main>
    </div>
  );
}
