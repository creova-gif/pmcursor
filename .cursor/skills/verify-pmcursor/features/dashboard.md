# Org alignment dashboard (`pmcursor dashboard`)

## Sub-features

- Compute `OrgDashboardSummary`: contract counts, alignment score, scope
  coverage percent, P0 checklist items, status — one rollup of repo health.
- Reads `--prd` (default `PROJECT_SPEC.md`).

## How to get to it (user POV)

A PM runs `pmcursor dashboard --repo .` for a one-glance summary instead of
reading the full drift report. `GET /v1/dashboard` is the API twin.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor dashboard --repo . --prd PROJECT_SPEC.md --json
echo $?   # expect 0
```

Proof of working: `OrgDashboardSummary` has `repo_root`, `models_count`,
`routes_count`, `telemetry_count`, `adrs_count`, `feature_flags_count`,
`alignment_score`, `scope_coverage_percent`, `p0_checklist_items`, `status`.
Verified: 56 models, 21 routes, 5 ADRs, 19 flags, score 76, DONE.

## Gotchas

- `scope_coverage_percent` is near-zero on this repo (1.2%) — the spec's
  scope list is small vs the repo surface; a low number is real, not a bug.
- `--prd` defaults to `PROJECT_SPEC.md`; a missing file errors, not a
  degraded report.
