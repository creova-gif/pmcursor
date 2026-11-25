---
name: pm-office-hours
description: Reframe product requests through diagnostic questions grounded in your repository's AST contracts and ADRs before writing a PRD or spec.
---

# pm-office-hours

Adapted from `garrytan/gstack` (`office-hours`) and `cursor/plugins` for technical product managers.

Do not write implementation code during `pm-office-hours`. Output a problem and scope memo grounded in repository contracts.

## Phase 1: Preflight contract scan

Before asking questions, index the repository contracts so you do not ask questions the codebase already answers:

```bash
python3 -m pmcursor.cli index --repo . --json
```

Cite existing models, API routes, and ADRs (`docs/adr/*.md`) in your opening summary.

## Phase 2: Six forcing questions

Ask at most 3 questions per turn until all 6 have concrete answers:
1. Which workflow failed recently, for which customer or `org_id`, and what did it cost?
2. Are we patching a symptom in the UI or API when the root constraint sits in the data model?
3. Which indexed models (`ModelContract`) and routes (`RouteContract`) already cover most of this request?
4. What is the smallest version we can ship in 1 to 3 days to test demand?
5. Which metric or acceptance threshold proves the change worked?
6. Which adjacent requests are out of scope for this cycle?

## Phase 3: Decision memo and handoff

Write the product memo with:
- Problem statement and smallest shippable scope.
- Impacted code contracts with `file:line` citations.
- Implementation options with effort estimates per component.
- Completion status: `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`.
- Next step: run `/pm-spec` to draft the PRD and verify it with `pmcursor drift`.
