# pmcursor execution checklist

## Wave 1: Day 1 to 5 setup
- [x] Set up `indexer/`, `api/`, `web/`, and `evals/` directories
- [x] Build AST and Pydantic extractor outputting a JSON map of models, routes, and ADRs (`src/pmcursor/indexer.py`)
- [x] Implement `check_spec_drift(prd_md, repo_map)` flagging mismatches with exact `file:line` citations (`src/pmcursor/drift.py`)
- [x] Test on a FastAPI and Pydantic reference codebase and verify zero hallucinated file paths (`evals/benchmark.py`)

## Wave 2: MVP and eval gate
- [x] Write `ADR-001` and `ADR-002` in `docs/adr/`
- [x] Package PMCursor as a Cursor and Claude plugin (`.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`, `rules/`, `skills/`, `agents/`)
- [x] Implement core pipeline and deterministic unit and eval tests (`tests/test_smoke.py`)
- [x] Verify CI workflow passes (`ruff check`, `mypy --strict`, `pytest`)

## Wave 3: Launch and design partner validation
- [x] Publish clean `README.md` with reproducible benchmark numbers and `cursor/plugins` plus `gstack` architecture mapping
- [ ] Run first external design-partner or open-source release

## Scope expansion (T1 to T6)
- [x] **T1 (`SEC-1`)**: Enforce `repo_root` path containment, `(OSError, UnicodeDecodeError)` rescue, and `2MB` file cap in `src/pmcursor/indexer.py` and `src/pmcursor/drift.py`
- [x] **T2 (`EXP-1`)**: Add `Zod`, `Next.js` App Router, `OpenAPI`, and `SQL` DDL extractors in `src/pmcursor/indexer.py`
- [x] **T3 (`EXP-4`)**: Add `TelemetryContract` indexing (`track_event`, `PostHog`, `Vercel Analytics`, `Langfuse`, `BigQuery`) and PRD `telemetry:` drift checks
- [x] **T4 (`EXP-2`)**: Implement `fix_prd_markdown` and `pmcursor fix-prd` in `src/pmcursor/drift.py` and `src/pmcursor/cli.py`
- [x] **T5 (`EXP-3`)**: Implement `verify_github_signature`, `compute_pr_impact`, and `pmcursor pr-impact` in `api/__init__.py` and `src/pmcursor/cli.py`
- [x] **T6 (`EXP-5`)**: Implement `render_split_pane_canvas` and `pmcursor canvas` in `web/canvas.py` and `src/pmcursor/cli.py`
- [x] Verify test suite (`PYTHONPATH=src:. pytest`: `10 passed`)
