# Evaluation benchmark (`pmcursor eval`)

## Sub-features

- Run the deterministic eval harness: seed 5 spec-vs-code mismatches + 2
  fabricated citations into a synthetic repo and measure drift recall.
- Gate: `>=85%` recall on seeded mismatches and 0 unflagged fabricated
  citations.
- `--json` emits the eval result.

## How to get to it (user POV)

A maintainer runs `pmcursor eval` to prove the drift engine catches planted
bugs before shipping — this is the acceptance threshold from PROJECT_SPEC.md
and runs in `release.yml`.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor eval --json
echo $?   # expect 0 when passed=true
```

Proof of working: `passed: true`, `seeded_mismatches: 5`,
`detected_mismatches: 5`, `recall: 1.0`,
`seeded_fabricated_citations: 2`, `detected_fabricated_citations: 2`,
`unflagged_fabricated_citations: 0`, plus an `alignment_score`. Verified
recall 1.0 / score 64.

## Gotchas

- The eval synthesizes its own fixture repo — it does not audit this repo, so
  results don't change as the product grows.
- `alignment_score` is a secondary metric, not the gate; `passed` is the gate.
