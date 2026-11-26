---
name: pm-drift
description: Run deterministic PRD-vs-codebase drift verification to flag missing models, field type mismatches, route discrepancies, and fabricated file:line citations.
---

# pm-drift

Checks a PRD or spec against the repository's AST contracts to catch schema mismatches and fabricated `file:line` citations.

## Steps

1. Run the CLI drift audit in Markdown or JSON mode:
   ```bash
   python3 -m pmcursor.cli drift --prd <path-to-prd.md> --repo . --md
   ```
   For CI pipelines that fail on drift:
   ```bash
   python3 -m pmcursor.cli drift --prd <path-to-prd.md> --repo . --json --fail-on-drift
   ```
   To audit Linear or Jira ticket specs against the `RepoMap` alongside PRD drift checks, run `pmcursor ticket-sync`:
   ```bash
   python3 -m pmcursor.cli ticket-sync --id <TICKET-ID> --title "<Title>" --body-file <ticket.md> --repo .
   ```

2. Review findings by category:
   - `fabricated_citation`: A `path/to/file.py:line` reference where the file is missing or the line number exceeds the file length.
   - `missing_model`: A model in the PRD (`ModelName.field: type`) that is absent from the codebase AST.
   - `missing_field`: A field on an existing model in the PRD that is missing in code, citing the model's `file:line`.
   - `type_mismatch`: A field whose PRD type differs from the code annotation, citing the field's `file:line`.
   - `missing_route` or `method_mismatch`: An endpoint (`METHOD /path`) missing from FastAPI routers or registered with a different HTTP verb.

3. Check the spec alignment score (`0` to `100`):
   - Deterministic contract score (`70%` weight): citation accuracy plus model, field, and route match rate.
   - Workflow readiness score (`30%` weight): ADR references, `protects/fails_when/no_claim` test cards, out of scope section, and rollback section.

4. Update the PRD or create implementation tasks to resolve each finding. Report status with `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`.
