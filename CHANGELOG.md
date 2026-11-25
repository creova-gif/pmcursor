# Changelog

All notable changes to PMCursor are documented in this file.

## v0.1.0 (2026-11-25)

### Added

- Implemented `EXP-1` contract extractors for Zod schemas, Next.js App Router routes, OpenAPI specifications, and SQL DDL tables in `src/pmcursor/indexer.py`, alongside Pydantic models, FastAPI routes, and architecture decision records.
- Implemented `EXP-2` automated PRD repair via `fix_prd_markdown` in `src/pmcursor/drift.py` and the `pmcursor fix-prd` CLI subcommand.
- Implemented `EXP-3` pull request impact analysis via `verify_github_signature` and `compute_pr_impact` in `api/__init__.py` and the `pmcursor pr-impact` CLI subcommand.
- Implemented `EXP-4` telemetry contract indexing for `track_event`, PostHog, Vercel Analytics, Langfuse, and BigQuery, plus PRD `telemetry:` drift checks.
- Implemented `EXP-5` interactive split-pane HTML spec canvas generation via `render_split_pane_canvas` in `web/canvas.py` and the `pmcursor canvas` CLI subcommand.
- Added CLI subcommands in `src/pmcursor/cli.py`: `index`, `drift`, `fix-prd`, `pr-impact`, `canvas`, `validate-plugin`, and `eval`.
- Packaged PMCursor as a Cursor and Claude plugin with `.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`, `rules/`, `skills/`, and `agents/`.

### Security

- Implemented `SEC-1` path containment within `repo_root`, `2MB` file size caps, and `(OSError, UnicodeDecodeError)` error handling in `src/pmcursor/indexer.py` and `src/pmcursor/drift.py`.

### Verification

- The test suite passed 10 of 10 tests via `PYTHONPATH=src:. pytest`.
- The evaluation benchmark reported 100.0% schema and route mismatch recall, 5 of 5, and 0 unflagged fabricated file citations, 2 of 2 caught, via `PYTHONPATH=src python3 -m pmcursor.cli eval --json`.
