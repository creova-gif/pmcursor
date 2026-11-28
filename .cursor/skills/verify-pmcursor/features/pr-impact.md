# PR impact analysis (`pmcursor pr-impact`)

## Sub-features

- Map a unified git diff to impacted `RepoMap` contracts and PRD references —
  answers "what does this PR touch?".
- Diff source: `--diff <file>` or `git diff <base>...HEAD` (`--base`, default
  `main`).
- `--org-id` sets the tenant label on the report (default `default`).
- `--md` (default) emits a GitHub PR comment body; `--json` emits
  `PRImpactReport`.

## How to get to it (user POV)

Before merging, a PM runs `pmcursor pr-impact --prd PROJECT_SPEC.md --repo .
--base main` to see which spec contracts the diff impacts — this is what the
GitHub App posts as a check run in M21/M22.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor pr-impact --prd PROJECT_SPEC.md --repo . --base v0.1.0 --json > impact.json
echo $?   # expect 0
```

Proof of working: `impact.json` is a `PRImpactReport`. Verified against
`v0.1.0..HEAD` — produced a real diff-grounded report (~17KB). The markdown
form is the body the GitHub App posts as a check-run comment.

## Gotchas

- `--base` must be a reachable git ref; a bad ref makes `git diff` fail.
- On a branch with no divergence from `--base`, the diff is empty and the
  report shows zero impacted contracts — correct, not a bug.
- `--org-id` only labels the report; the CLI is single-tenant.
