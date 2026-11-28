import type {
  DriftReport,
  EdgeCaseChecklist,
  RepoMap,
} from "@/lib/types";

async function postJson<T>(path: string, body: unknown): Promise<T> {
  const resp = await fetch(`/api/pmcursor/${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
    cache: "no-store",
  });
  if (!resp.ok) {
    const text = await resp.text();
    let detail = text.slice(0, 300);
    try {
      const parsed = JSON.parse(text) as { detail?: string };
      if (parsed.detail) detail = parsed.detail;
    } catch {
      // keep raw text
    }
    throw new Error(`PMCursor API ${resp.status}: ${detail}`);
  }
  return (await resp.json()) as T;
}

export function runDriftAudit(args: {
  prd_markdown: string;
  repo_root: string;
  prd_path: string;
}): Promise<DriftReport> {
  return postJson<DriftReport>("drift/audit", args);
}

export function indexRepo(repo_root: string): Promise<RepoMap> {
  return postJson<RepoMap>("index", { repo_root });
}

export function generateChecklist(args: {
  prd_markdown: string;
  repo_root: string;
}): Promise<EdgeCaseChecklist> {
  return postJson<EdgeCaseChecklist>("checklist", args);
}
