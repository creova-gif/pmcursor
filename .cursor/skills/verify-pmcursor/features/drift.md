# Spec drift audit

## Sub-features

- Compare a PRD/spec markdown file against the indexed `RepoMap` and report
  findings: missing models, field type mismatches, route discrepancies,
  fabricated `file:line` citations, telemetry gaps.
- Output formats: `--md` (default Markdown report), `--json`
  (`DriftReport`), `--sarif` (SARIF 2.1.0 for GitHub Code Scanning).
- `--fail-on-drift` exits `1` when any finding or fabricated citation exists —
  this is the CI gate.

## How to get to it (user POV)

A PM writes a PRD, then runs `pmcursor drift --prd PROJECT_SPEC.md --repo .`
before shipping to check the spec still matches the code. In CI the same check
runs with `--fail-on-drift` to block merges. The equivalent API call is
`POST /v1/drift/audit`.

## Driving it with the pmcursor CLI + curl

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor drift --prd PROJECT_SPEC.md --repo . --json > drift.json
echo $?   # expect 0 (no --fail-on-drift)
```

Proof of working: `drift.json` is a `DriftReport` with keys `prd_path`,
`status`, `alignment_score`, `total_citations_checked`,
`fabricated_citations_count`, `findings`. `status` is `DONE` on a completed
audit.

Via the API (server up per `../SKILL.md`):

```bash
curl -sf -X POST http://127.0.0.1:8123/v1/drift/audit \
  -H 'Content-Type: application/json' \
  -d "$(python3 - <<'PY'
import json
print(json.dumps({
    "prd_markdown": open("PROJECT_SPEC.md").read(),
    "repo_root": ".",
    "prd_path": "PROJECT_SPEC.md",
}))
PY
)" > drift-response.json
```

Same `DriftReport` shape back; side effect to capture: `GET /readyz` then
reports `cached_repos` incremented — the index cache engaged.

## Gotchas

- `PROJECT_SPEC.md` currently contains no `file:line` citations, so
  `total_citations_checked` is `0` and `fabricated_citations_count` is `0`.
  That is a real result, not a skipped check. To exercise citation validation,
  the spec file must cite paths like `src/pmcursor/indexer.py:12`.
- A PRD that cites a non-existent file produces a finding and `--fail-on-drift`
  exits `1` — when proving the gate, capture `echo $?` and the finding text,
  not just the exit code.
- `repo_root` in the API body resolves relative to the *server's* cwd, not the
  curl client's. `up.sh` starts the server from the repo root, so `"."` works.
- `--sarif` prints SARIF to stdout like `--json`; do not combine both expecting
  two outputs.
