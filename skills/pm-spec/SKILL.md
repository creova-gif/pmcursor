---
name: pm-spec
description: Author a codebase-verified PRD or engineering spec in five phases with verified file:line citations, schema contracts, and acceptance cards.
---

# pm-spec

Combines the 5-phase interrogation from `garrytan/gstack` (`spec`) with PMCursor's AST contract indexer (`pmcursor index`) and structured sections from `cursor/plugins` (`docs-canvas`).

Never produce a final PRD on the first turn without running `pmcursor index` and checking every cited `file:line`.

## Phase 1: Understand the problem
Confirm and record:
1. Who is affected (role and tenant scope).
2. What the current behavior is, with `file:line` citations.
3. What the target behavior and measurable acceptance threshold are.
4. Why this work matters now.

## Phase 2: Scope, non-goals, and rollback
Lock explicit out of scope items, ordering constraints, and the rollback plan before drafting schemas.

## Phase 3: AST contract check
Run the contract indexer:

```bash
python3 -m pmcursor.cli index --repo . --json
```

Compare every proposed model, field (`Model.field: type`), and endpoint (`METHOD /path`) against the indexed `RepoMap`. Cite exact `file:line` locations for every existing contract touched.

## Phase 4: Spec draft
Include these sections:
1. Overview and stakeholder context.
2. Verified current state table with `file:line` citations.
3. Contract specifications:
   - Models and fields formatted as `` `ModelName.field_name: type` ``.
   - Endpoints formatted as `` `METHOD /route/path` ``.
   - File reference table (`path/to/file.py:line`).
4. Acceptance criteria cards:
   - Each test states `protects=<observable>; fails_when=<failure condition>; no_claim=<unverified boundary>`.
5. Out of scope and rollback plan.

## Phase 5: Drift and citation gate
Run the drift check before finishing the spec:

```bash
python3 -m pmcursor.cli drift --prd <spec-path> --repo . --md
```

Report completion with `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`.
