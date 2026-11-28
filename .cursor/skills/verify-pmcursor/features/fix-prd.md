# PRD repair (`pmcursor fix-prd`)

## Sub-features

- Repair shifted `file:line` citations and mismatched `Model.field` types in a
  PRD against the indexed `RepoMap`.
- `--dry-run` (default) previews repairs without touching the file; `--write`
  applies them in place.
- `--json` emits `FixPrdResult`.

## How to get to it (user POV)

A PM's drift audit shows citations pointing at wrong lines after code moved.
Instead of hand-editing, they run `pmcursor fix-prd --prd PRD.md --repo .
--write` to repair the spec mechanically.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor fix-prd --prd <path-to-prd.md> --repo . --dry-run --json
echo $?   # expect 0
```

Proof of working: the `FixPrdResult` JSON has `prd_path`,
`updated_markdown`, `fixed_citations_count`, `fixed_types_count`, and
`applied`. With `--dry-run`, `applied` is `false` and the file is unchanged;
`updated_markdown` is the would-be result. A well-formed PRD yields
`fixed_citations_count: 0` — zero repairs is a real result, not a skip.

## Gotchas

- The command never fails on a clean PRD — it exits 0 with zero fixes.
- `--write` and `--dry-run` are mutually exclusive; passing neither defaults
  to dry-run.
- Repair only covers citation line numbers and `Model.field` type text — it
  does not rewrite prose.
