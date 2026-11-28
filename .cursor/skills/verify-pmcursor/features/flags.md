# Feature-flag audit (`pmcursor flags`)

## Sub-features

- Extract feature-flag references from the repo (LaunchDarkly, Statsig,
  Unleash, generic call sites) into `Flag` records.
- With `--prd`, run `audit_feature_flags_and_rollout` — verify the spec's
  rollout and rollback readiness against indexed flags (`FlagAuditReport`).
- `--json` emits machine-readable output.

## How to get to it (user POV)

A PM runs `pmcursor flags --repo .` to inventory every flag in the codebase,
or adds `--prd PROJECT_SPEC.md` to check the PRD's rollout plan against the
flags that actually exist. `POST /v1/flags/audit` is the API twin.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor flags --repo . --json > flags.json
echo $?   # expect 0
```

Proof of working: extract mode emits flag records. Verified: 19 flag
references found in this repo (`feature_flags_count: 19` on the dashboard).
With `--prd` the output is a `FlagAuditReport`.

## Gotchas

- Extract mode (`--repo` alone) never touches the spec — it just inventories
  flags, so it always exits 0 even with zero flags found.
- This repo's flags are indexer fixtures, not live product flags — a nonzero
  count is correct.
