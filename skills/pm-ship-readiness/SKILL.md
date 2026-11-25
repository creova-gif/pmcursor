---
name: pm-ship-readiness
description: Pre-release quality gate verifying plugin manifests, spec-drift alignment, ADR coverage, static analysis (ruff, mypy), and deterministic eval benchmarks.
---

# pm-ship-readiness

Runs the pre-release verification suite adapted from `garrytan/gstack` (`ship`) and `cursor/plugins` (`review-plugin-submission`).

## Run all checks

```bash
python3 -m pmcursor.cli validate-plugin --repo . && \
python3 -m pmcursor.cli eval --json && \
pytest
```

## Checklist

1. Plugin manifest gate: `.cursor-plugin/plugin.json` and `.claude-plugin/plugin.json` exist, versions match `pyproject.toml`, and all declared component directories (`./skills/`, `./agents/`, `./rules/`) contain files with valid YAML frontmatter.
2. Evaluation benchmark gate: `0` unflagged fabricated file citations and at least `85%` recall on seeded spec-vs-code mismatches.
3. Engineering standards gate: `docs/adr/` records architectural decisions, and `ruff check`, `mypy --strict`, and `pytest` pass with zero errors.

## Report format

End with:
- Status: `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`.
- Metrics: mismatch recall percentage, fabricated citations caught, and plugin validation status.
- Commands run and exit codes observed.
