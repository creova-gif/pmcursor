## Summary

<!-- Describe what this PR changes and why. Link any related issues (e.g., Fixes #123). -->

## Verification Checklist

- [ ] `uvx ruff check src indexer api web evals tests`
- [ ] `MYPYPATH=src mypy --strict src indexer api web evals tests`
- [ ] `pytest -v`
- [ ] `PYTHONPATH=src python3 -m pmcursor.cli validate-plugin --repo .`
- [ ] `PYTHONPATH=src python3 -m pmcursor.cli eval --json`

## ADR Check

- [ ] Does this PR introduce a non-trivial architectural or design decision? If yes, an ADR has been added under `docs/adr/` using `docs/adr/000-template.md` (or explain below why no ADR is needed).
