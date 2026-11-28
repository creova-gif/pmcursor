# Drift summarizer (`pmcursor summarize`)

## Sub-features

- Turn a drift audit into a PM-facing `PMDriftSummary` — ship recommendation,
  headline, narrative markdown.
- `method` is `deterministic` (offline template) or `anthropic` (Claude when
  `pmcursor[llm]` + `ANTHROPIC_API_KEY`); `--offline` forces the template.
- Ship recommendation, top risks, and spec edits are always deterministic —
  Claude only writes the narrative; `--json` emits `PMDriftSummary`.

## How to get to it (user POV)

A PM runs `pmcursor summarize --prd PROJECT_SPEC.md --repo .` to get the
one-paragraph answer instead of the full `DriftReport`. `POST /v1/summarize`
is the API twin.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor summarize --prd PROJECT_SPEC.md --repo . --offline --json
echo $?   # expect 0
```

Proof of working: `PMDriftSummary` has `prd_path`, `method`,
`ship_recommendation`, `headline`, `narrative_markdown`. Verified offline:
`method: "deterministic"`, `ship_recommendation: "ship"`, headline "Spec is
aligned — PROJECT_SPEC.md scores 76/100".

## Gotchas

- `--offline` makes the proof deterministic and credential-free — always use
  it for verification.
- Without `--offline` and without `pmcursor[llm]` installed it still falls
  back to the template (no error) — `method` in the output says which ran.
- `ship_recommendation` comes from the deterministic engine, never from the
  LLM — an LLM outage can only affect the narrative text.
