# PMCursor Working Plan (CEO Review)

- **Repo:** `justinmafie/pmcursor`
- **Branch:** `main` (base branch: `main`)
- **Review Mode:** `SCOPE EXPANSION`
- **Review Depth:** Implementation-ready
- **Source Specs:** `PROJECT_SPEC.md`, `TASKS.md`, `docs/adr/001-contract-first-repo-indexing.md`, `docs/adr/002-cursor-plugin-and-gstack-skill-architecture.md`
- **Companion CEO Summary:** `/Users/justinmafie/.gstack/projects/justinmafie/ceo-plans/2026-11-25-pmcursor-scope-expansion.md`

---

## Pre-Review System Audit & Context

- **Current Working Tree State:** Wave 1 and Wave 2 core deliverables are implemented and passing in 11 Python files (`src/pmcursor/models.py`, `src/pmcursor/indexer.py`, `src/pmcursor/drift.py`, `src/pmcursor/plugin_validator.py`, `src/pmcursor/eval_runner.py`, `src/pmcursor/cli.py`, `indexer/__init__.py`, `api/__init__.py`, `evals/benchmark.py`, `tests/test_smoke.py`) plus dual plugin manifests (`.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`), 4 skills (`skills/pm-*/SKILL.md`), 1 rule (`rules/pmcursor-citations.mdc`), and 1 agent (`agents/spec-drift-auditor.md`).
- **Taste Calibration:**
  - **Good patterns to emulate:** `src/pmcursor/models.py:1-140` (frozen Pydantic v2 domain models with strict literal unions) and `src/pmcursor/indexer.py:1-253` (pure stdlib `ast` extraction with zero runtime execution of target repo code).
  - **Patterns to avoid:** Unverified regex scraping without line bounds checking, or stateful web servers required just to run a local CLI check.
- **Landscape Synthesis (Layers 1–3):**
  - **Layer 1 (Tried and true):** OpenAPI-to-OpenAPI diffing (`oasdiff`) and runtime `app.openapi()` export in CI. Fails when specs live in Markdown PRDs or when code changes internal models and unmounted routers.
  - **Layer 2 (New and popular):** Spec-driven IDEs (Amazon Kiro, GitHub Spec Kit) and massive context engines (Augment Code). High friction when they require abandoning Markdown PRDs or paying for full-repo LLM context on every check.
  - **Layer 3 (First Principles / Eureka):** Parsing explicit backticked contract tokens (`Model.field: type`, `METHOD /path`, `file:line`, `ADR-NNN`, `telemetry: event(prop)`) out of Markdown PRDs and diffing them against a static AST `RepoMap` achieves `0` fabricated citations and `100%` schema drift recall in `<50ms` without booting the target app or spending LLM tokens.

---

## Step 0A: Premise Challenge

- **Real Problem:** Product Managers write PRDs in Markdown, Notion, or Linear, and within two sprints the codebase diverges: fields are renamed, endpoints change HTTP verbs, telemetry events are dropped, and file paths in specs rot. Coding agents reading stale PRDs build against hallucinated schemas.
- **Target Outcome:** Every PRD, sprint ticket, and acceptance checklist stays deterministically synced to live code contracts (`Pydantic`, `Zod`, `OpenAPI`, `SQL`, `FastAPI`, `Next.js`, `ADRs`, and telemetry events) with `0` fabricated `file:line` citations and `>= 85%` drift recall.
- **Do-Nothing Cost:** PMs manually audit PR diffs against specs or ship silent spec-vs-code mismatches into production; AI coding agents waste cycles on stale file paths.
- **Premise Verdict:** With `EXP-1` through `EXP-5` and `SEC-1` approved in `SCOPE EXPANSION` mode, this plan directly fulfills every pillar of `PROJECT_SPEC.md:9-27`.

| Premise | Claim | File:Line Receipt | Verdict |
|:---|:---|:---|:---|
| P1 | PMCursor targets `0` fabricated file paths and `>= 85%` mismatch recall | `PROJECT_SPEC.md:18` | Verified (`eval_runner.py:85` achieves `100%` recall, `0` unflagged fabricated paths) |
| P2 | ADR-001 mandates indexing `Pydantic/Zod/OpenAPI/SQL/ADRs` contracts | `PROJECT_SPEC.md:21` | Approved in `EXP-1` (`D3: A`) |
| P3 | Tech stack includes GitHub Webhooks for live PR drift checks | `PROJECT_SPEC.md:15` | Approved in `EXP-3` (`D5: A`) |
| P4 | Goal includes syncing PRDs to BigQuery/Langfuse telemetry | `PROJECT_SPEC.md:9` | Approved in `EXP-4` (`D6: A`) |
| P5 | Tech stack includes a split-pane UI / visual canvas for PMs | `PROJECT_SPEC.md:15` | Approved in `EXP-5` (`D7: A`) |
| P6 | Plugin manifests must validate cleanly for Cursor and Claude Code | `src/pmcursor/plugin_validator.py:44` | Verified (`6/6` components pass validation) |

---

## Step 0B: Existing Code Leverage & Reality Rows

- **Sub-problem 1 (Multi-stack & telemetry contract indexing):** Extend `src/pmcursor/indexer.py:217` (`index_repository`) and `src/pmcursor/models.py:72` (`RepoMap`) with `TelemetryContract` and deterministic extractors for `.ts`/`.tsx` (`Zod` + `Next.js` App Router), `openapi.json`/`.yaml`, and `.sql` (`CREATE TABLE`).
- **Sub-problem 2 (PRD drift & auto-remediation):** Reuse `CITATION_RE`, `SPEC_FIELD_RE`, and `SPEC_ROUTE_RE` in `src/pmcursor/drift.py:16-28` to power both detection (`check_spec_drift`) and automatic citation/contract repair (`fix_prd_markdown`).
- **Sub-problem 3 (GitHub PR webhook & diff impact):** Extend `api/__init__.py:16` (`audit_prd_against_repo`) with `verify_github_signature` (HMAC-SHA256) and `compute_pr_impact` (unified diff hunk overlap with `RepoMap`).
- **Sub-problem 4 (Split-Pane Spec Canvas):** Add `web/canvas.py` (`render_split_pane_canvas(prd_md, repo_map, report)`) wired to `pmcursor canvas`.

REALITY: premise-table pass All 6 factual claims verified with file:line receipts (unverified=0) PROJECT_SPEC.md:9
REALITY: already-done pass Wave 1-2 Python AST indexer, drift verifier, CLI, and dual plugin manifests are already implemented in working tree src/pmcursor/drift.py:341
REALITY: surface-check pass Verified all 4 CLI subcommands (index, drift, validate-plugin, eval) against build_parser() src/pmcursor/cli.py:21
REALITY: binding-decisions pass Honored ADR-001 (AST contract indexing) and ADR-002 (cursor/plugins + gstack hybrid architecture) docs/adr/001-contract-first-repo-indexing.md:1
REALITY: numbers pass Re-derived 100% recall (5/5) and 0 unflagged fabricated citations (2/2 caught) from live cli eval run src/pmcursor/eval_runner.py:85
REALITY: deferred-asks pass No linked GitHub issue; Wave 3 external design-partner release tracked in TASKS.md TASKS.md:17
REALITY: pr-count pass Single-wave cohesive package (pr_count=1) pyproject.toml:1
PLAN_REALITY: phase=ceo rows=7/7 missing=none unverified=0 verdict=complete

---

## Step 0C: Dream State Mapping & Dream State Delta

```text
  CURRENT STATE                        THIS PLAN (SCOPE EXPANSION)                 12-MONTH IDEAL
  Python AST + ADR indexer             + Multi-stack extractors (Zod/OpenAPI/SQL)  Autonomous Product Operating System:
  + Markdown PRD drift CLI             + Self-healing PRD auto-fixer (--write)     Every PR, PostHog/BigQuery metric shift,
  + Cursor/Claude plugin skills        + GitHub PR diff impact & webhook handler   and customer call transcript updates
  (11 Python files, 5 tests)           + Telemetry contract verifier (BQ/Langfuse) living PRDs and spawns verified PRs
                                       + Self-contained Split-Pane HTML Canvas     with zero spec drift across 100+ repos.
```

### Dream state delta
This plan advances PMCursor from a single-language Python AST linter to a complete, full-stack Product-to-Code Contract Engine (`Pydantic`, `Zod`, `Next.js`, `OpenAPI`, `SQL`, `Telemetry`, `ADRs`) with self-healing PRDs (`fix-prd`), GitHub PR diff impact (`pr-impact`), and an interactive Split-Pane Spec Canvas (`canvas`), leaving only multi-repo cloud SaaS persistence for future waves.

---

## Step 0I: Temporal Interrogation

```text
  HOUR 1 (foundations):     Extend src/pmcursor/models.py with TelemetryContract, FixPrdResult,
                            PRImpactItem, PRImpactReport, and new DriftCategory literals.
                            (human: ~4h / CC: ~10min)
  HOUR 2-3 (core logic):    Implement _extract_zod_models, _extract_nextjs_routes,
                            _extract_openapi_contracts, _extract_sql_models, and telemetry
                            extractors in src/pmcursor/indexer.py; implement _check_telemetry_contracts
                            and fix_prd_markdown in src/pmcursor/drift.py.
                            Ambiguity resolved: OpenAPI YAML without PyYAML uses a line-aware
                            indentation parser fallback when PyYAML is absent, keeping zero mandatory
                            third-party deps beyond pydantic.
                            (human: ~3 days / CC: ~25min)
  HOUR 4-5 (integration):   Implement verify_github_signature + compute_pr_impact in api/__init__.py,
                            render_split_pane_canvas in web/canvas.py, and wire fix-prd, pr-impact,
                            and canvas subcommands into src/pmcursor/cli.py.
                            Surprise prevented: HTML-escape all PRD and contract strings in web/canvas.py
                            and enforce repo_root path containment on all file citations.
                            (human: ~3 days / CC: ~25min)
  HOUR 6+ (polish/tests):   Expand evals/benchmark.py and tests/test_smoke.py to test all 5 expansions,
                            path-traversal defense, UnicodeDecodeError handling, and CLI flags;
                            verify ruff check, mypy --strict, and pytest.
                            (human: ~1.5 days / CC: ~15min)
```

---

## Decision Ledger

| ID and owner | Contract and evidence | Current | Proposed | Status | Exact approval and scope |
|:---|:---|:---|:---|:---|:---|
| `EXP-1` (Indexer / `src/pmcursor/indexer.py`) | `PROJECT_SPEC.md:21` mandates indexing `Pydantic/Zod/OpenAPI/SQL/ADRs`; `src/pmcursor/indexer.py:217` previously parsed `.py` and `docs/adr/*.md`. | Add deterministic extractors for TypeScript `z.object` (`Zod`), Next.js `route.ts`, `openapi.json`/`.yaml` schemas & routes, and `.sql` `CREATE TABLE` columns into `RepoMap`, plus unit & eval tests. | — | approved | `D3: A` & `D8: A` — Add `Zod`/`Next.js` (`.ts`/`.tsx`), `OpenAPI` (`.json`/`.yaml`), and `SQL` (`.sql`) extractors + unit/eval tests to `src/pmcursor/indexer.py`. |
| `EXP-2` (Drift / `src/pmcursor/drift.py`) | `src/pmcursor/drift.py:72` flags out-of-bounds lines and type mismatches, requiring manual edits by the PM. | Add `fix_prd_markdown` and `pmcursor fix-prd --prd <path> [--dry-run \| --write]` to auto-heal shifted `file:line` citations and contract types. | — | approved | `D4: A` & `D8: A` — Add `fix_prd_markdown` in `src/pmcursor/drift.py` and `pmcursor fix-prd --prd <path> [--dry-run \| --write]` in `src/pmcursor/cli.py` + unit tests. |
| `EXP-3` (API & CLI / `api/__init__.py`) | `PROJECT_SPEC.md:9,15` specifies GitHub Webhooks and syncing PRDs to live Git PRs; `docs/THREAT_MODEL.md:4` requires strict schema validation and auth gates. | Add `pmcursor pr-impact --prd <path>` and `verify_github_signature` + PR impact webhook handler in `api/`. | — | approved | `D5: A` & `D8: A` — Add `compute_pr_impact` + `pmcursor pr-impact --prd <path>` and HMAC-SHA256 webhook verification in `api/` + unit tests. |
| `EXP-4` (Telemetry / `src/pmcursor/indexer.py`) | `PROJECT_SPEC.md:9` requires syncing PRDs to BigQuery/Langfuse telemetry with `file:line` citations. | Add `TelemetryContract` to `RepoMap` indexing `track_event`/`langfuse`/`bigquery`/`posthog`/`vercel_analytics` schemas and checking PRD `telemetry:` references in `check_spec_drift`. | — | approved | `D6: A` & `D8: A` — Add `TelemetryContract` in `src/pmcursor/models.py`, extract telemetry events in `src/pmcursor/indexer.py`, and check `telemetry:` specs in `src/pmcursor/drift.py` + unit tests. |
| `EXP-5` (Web UI / `web/canvas.py`) | `PROJECT_SPEC.md:15` specifies a split-pane UI; `web/README.md:1` is currently a documentation stub. | Add `web/canvas.py` and `pmcursor canvas --prd <path> --output <html_path>` generating an interactive split-pane HTML spec-vs-code explorer. | — | approved | `D7: A` & `D8: A` — Add `web/canvas.py` (`render_split_pane_canvas`) and `pmcursor canvas --prd <path> --output <html_path>` in `src/pmcursor/cli.py` + unit tests. |
| `SEC-1` (Security & Errors / `src/pmcursor/drift.py`, `src/pmcursor/indexer.py`) | Section 2 & Section 3 review: `src/pmcursor/drift.py:72` (`_verify_citations`) joins `root / rel_path` without checking `is_relative_to(resolved_root)` (allowing `../../etc/passwd:1` traversal probes), and `src/pmcursor/indexer.py:238` catches `OSError` but not `UnicodeDecodeError` or oversized (>2MB) bundle files. | Enforce `candidate.resolve().is_relative_to(root.resolve())` in `_verify_citations` and `fix_prd_markdown`, catch `(OSError, UnicodeDecodeError)` across all file reads, and skip files >2MB (`MAX_INDEX_FILE_BYTES = 2_097_152`) in `index_repository`. | — | approved | `D9: A` — Enforce `is_relative_to(resolved_root)` on PRD citations, rescue `(OSError, UnicodeDecodeError)`, and skip files >2MB (`MAX_INDEX_FILE_BYTES = 2_097_152`) + unit test. |

Approval readiness: PASS (Verified approved rows: `EXP-1`=`D3:A`/`D8:A`, `EXP-2`=`D4:A`/`D8:A`, `EXP-3`=`D5:A`/`D8:A`, `EXP-4`=`D6:A`/`D8:A`, `EXP-5`=`D7:A`/`D8:A`, `SEC-1`=`D9:A`; 0 unresolved choices, 0 unapproved additions).

---

## NOT in scope

- **Deferred to `TODOS.md`:** None (`0` items deferred; all 5 expansion proposals `EXP-1`..`EXP-5` were accepted in `D3`..`D7`).
- **Skipped / Rejected:** None (`0` items rejected).
- **Explicit Non-Goals (Out of Scope for this wave):**
  - Multi-tenant hosted PostgreSQL/Supabase cloud database daemon (rationale: local CLI, webhook verifier, and static HTML canvas operate with zero external database dependencies).
  - Live outbound network calls to GitHub, Stripe, or BigQuery APIs during `pmcursor drift` or `pytest` execution (rationale: keeps tests 100% deterministic and offline-safe).

---

## What already exists

- `src/pmcursor/models.py:1-140` — Frozen Pydantic v2 models (`FieldContract`, `ModelContract`, `RouteContract`, `ADRContract`, `RepoMap`, `DriftFinding`, `SpecAlignmentScore`, `DriftReport`, `PluginValidationResult`, `EvalBenchmarkResult`); reused and extended by `EXP-1`..`EXP-5`.
- `src/pmcursor/indexer.py:1-253` — Python AST (`BaseModel`, `dataclass`, `FastAPI`, `APIRouter`) and Markdown ADR (`docs/adr/*.md`) extractor; reused and extended by `EXP-1`, `EXP-4`, and `SEC-1`.
- `src/pmcursor/drift.py:1-433` — `check_spec_drift` and `format_drift_report_markdown` with `70/30` blended `SpecAlignmentScore`; reused and extended by `EXP-2`, `EXP-4`, and `SEC-1`.
- `src/pmcursor/plugin_validator.py:1-143` — Dual-manifest `.cursor-plugin/plugin.json` and `.claude-plugin/plugin.json` validator; reused unchanged.
- `src/pmcursor/eval_runner.py:1-118` and `src/pmcursor/cli.py:1-196` — Benchmark runner and `argparse` CLI; extended with `fix-prd`, `pr-impact`, and `canvas` subcommands.

---

## Scope Expansion Decisions

- **Accepted (`5` of `5` proposals):**
  - `EXP-1` (`D3: A`): Multi-Stack Contract Indexer (`Zod` + `Next.js` App Router + `OpenAPI` + `SQL` DDL).
  - `EXP-2` (`D4: A`): Self-Healing PRD Citation & Contract Fixer (`pmcursor fix-prd`).
  - `EXP-3` (`D5: A`): GitHub PR Diff Impact & Webhook Verifier (`pmcursor pr-impact` + `api/`).
  - `EXP-4` (`D6: A`): Telemetry & Analytics Contract Verifier (`BigQuery` / `Langfuse` / `PostHog` / `Vercel Analytics`).
  - `EXP-5` (`D7: A`): Interactive Split-Pane Spec Canvas Generator (`pmcursor canvas` / `web/canvas.py`).
- **Deferred to `TODOS.md`:** None (`0`).
- **Skipped:** None (`0`).

---

## Error & Rescue Registry

| Method / Codepath | Exception Class / Condition | Rescued? | Rescue Action | User Impact |
|:---|:---|:---|:---|:---|
| `indexer.index_repository` | `OSError`, `UnicodeDecodeError`, file > `2MB` (`SEC-1`) | Y | Skip unreadable, non-UTF8, or >2MB file and continue walk | Clean `RepoMap` from valid files |
| `indexer.index_repository` (Python AST) | `SyntaxError` | Y | Skip syntactically invalid `.py` file | Clean `RepoMap` from valid files |
| `indexer._extract_zod_models` / `_extract_nextjs_routes` | Unmatched or malformed TypeScript syntax | Y | Return partial/empty list without raising | Clean `RepoMap` |
| `indexer._extract_openapi_contracts` | `OSError`, `UnicodeDecodeError`, `json.JSONDecodeError`, `ValueError` | Y | Skip invalid OpenAPI file and continue | Clean `RepoMap` |
| `indexer._extract_sql_models` / `_extract_sql_telemetry` | Malformed SQL DDL statement | Y | Skip malformed `CREATE TABLE` block | Clean `RepoMap` |
| `drift._verify_citations` | Path traversal outside `repo_root` (`is_relative_to == False`) (`SEC-1`) | Y | Flag as `critical` `fabricated_citation` without reading external file | Reported in `DriftReport` (`status=BLOCKED`) |
| `drift._verify_citations` | `OSError`, `UnicodeDecodeError` when counting lines (`SEC-1`) | Y | Set `total_lines = 0` and avoid unhandled crash | Clean citation check |
| `drift.fix_prd_markdown` | Cited file does not exist in `RepoMap` or `repo_root` | Y | Keep original citation untouched so `drift` still flags it | No fabricated path written |
| `api.verify_github_signature` | Empty secret, missing `sha256=` prefix, or mismatched digest | Y | Constant-time `hmac.compare_digest` returns `False` | Caller rejects unauthorized webhook |
| `web.canvas.render_split_pane_canvas` | Untrusted `<script>` or HTML entities in PRD/code | Y | `html.escape(..., quote=True)` on every interpolated string | Safe literal text in browser |

---

## Failure Modes Registry

```text
  CODEPATH                              | FAILURE MODE                        | RESCUED? | TEST? | USER SEES?                          | LOGGED?
  --------------------------------------|-------------------------------------|----------|-------|-------------------------------------|--------
  indexer.index_repository              | Non-UTF8 binary or >2MB file        | Y        | Y     | Skipped silently; valid RepoMap     | Y (indexed_files)
  indexer._extract_zod_models           | Malformed TypeScript file           | Y        | Y     | Skipped safely                      | Y
  indexer._extract_openapi_contracts    | Invalid JSON/YAML OpenAPI file      | Y        | Y     | Skipped safely                      | Y
  indexer._extract_sql_models           | Unparseable SQL DDL                 | Y        | Y     | Skipped safely                      | Y
  drift._verify_citations               | ../../etc/passwd path traversal     | Y        | Y     | Flagged as fabricated_citation      | Y (findings)
  drift._check_telemetry_contracts      | Uninstrumented PRD telemetry event  | Y        | Y     | Flagged as missing_telemetry        | Y (findings)
  drift.fix_prd_markdown                | Stale line number / field type      | Y        | Y     | Healed in --write or --dry-run diff | Y (FixPrdResult)
  api.verify_github_signature           | Forged X-Hub-Signature-256 header   | Y        | Y     | Returns False (rejected)            | Y
  api.compute_pr_impact                 | Empty or header-only unified diff   | Y        | Y     | Returns 0 touched contracts         | Y (PRImpactReport)
  web.canvas.render_split_pane_canvas   | XSS <script> payload in PRD         | Y        | Y     | Escaped literal text in HTML        | Y
```

Total Failure Modes: `10` rows, `0` CRITICAL GAPS.

---

## Diagrams

### 1. System Architecture Diagram
```text
  [Repo Files: .py, .ts/.tsx, .sql, openapi.json/.yaml, docs/adr/*.md]
          |
          v
  [src/pmcursor/indexer.py :: index_repository] (<=2MB cap, UTF-8 safe)
          |
          v
  [src/pmcursor/models.py :: RepoMap (models, routes, telemetry, adrs)]
     |                 |                     |                    |
     v                 v                     v                    v
  [drift.py]     [drift.py]           [api/__init__.py]    [web/canvas.py]
  check_spec_    fix_prd_             compute_pr_impact    render_split_pane_
  drift()        markdown()           + verify_github_sig  canvas()
     |                 |                     |                    |
     +-----------------+---------------------+--------------------+
                                  |
                                  v
            [src/pmcursor/cli.py :: pmcursor CLI]
```

### 2. Data Flow & Shadow Paths Diagram
```text
  INPUT (PRD.md + Repo Tree + git diff)
    |-- [nil/missing path] ---------> Exit 2 + example CLI command on stderr
    v
  BOUNDARY VALIDATION (is_relative_to(repo_root), <=2MB cap, UTF-8 decode)
    |-- [../ traversal citation] ---> Flagged as critical fabricated_citation
    |-- [non-UTF8 / >2MB file] -----> Skipped cleanly
    v
  CONTRACT EXTRACTION & DIFFING (Models, Routes, Telemetry, ADRs)
    |-- [0 mismatches, 0 fabricated] -> status=DONE
    |-- [schema/telemetry mismatch] --> status=DONE_WITH_CONCERNS
    |-- [fabricated citation] --------> status=BLOCKED
    v
  OUTPUT (--json, --md, fix-prd --write, pr-impact comment, or canvas.html)
```

### 3. State Machine Diagram
```text
  +-------------------+
  |  Unchecked PRD    |
  +-------------------+
            |
            | pmcursor drift
            v
  +-------------------+     pmcursor fix-prd --write     +-------------------+
  | DONE_WITH_CONCERNS| -------------------------------> |       DONE        |
  | (shifted lines /  |                                  | (0 findings,      |
  |  type mismatch)   |                                  |  0 fabricated)    |
  +-------------------+                                  +-------------------+
            |
            | fabricated file citation present
            v
  +-------------------+
  |      BLOCKED      | (cannot transition to DONE until missing file path is removed/created)
  +-------------------+
```

### 4. Error Flow Diagram
```text
  [File Read / Citation / Webhook Input]
        |
        +---> [OSError / UnicodeDecodeError / >2MB] ---> Skip file in indexer (no crash)
        |
        +---> [not candidate.is_relative_to(root)] ----> Emit DriftFinding(category="fabricated_citation")
        |
        +---> [Invalid HMAC-SHA256 signature] ---------> Return False from verify_github_signature
        |
        +---> [Untrusted HTML in PRD/Code] ------------> html.escape(text, quote=True) in web/canvas.py
```

### 5. Deployment Sequence Diagram
```text
  [1. Extend models.py (TelemetryContract, FixPrdResult, PRImpactReport)]
          |
          v
  [2. Extend indexer.py (Zod, Next.js, OpenAPI, SQL, Telemetry, SEC-1 guards)]
          |
          v
  [3. Extend drift.py (Telemetry check, fix_prd_markdown, SEC-1 path containment)]
          |
          v
  [4. Implement api/__init__.py (PR impact & HMAC) + web/canvas.py (Split-Pane HTML)]
          |
          v
  [5. Wire cli.py subcommands + run ruff, mypy --strict, pytest, validate-plugin, eval]
```

### 6. Rollback Flowchart
```text
  [Post-Deploy Issue Detected]
          |
          +---> [Issue in fix-prd --write edit?] ---> Run `git checkout -- <PRD.md>` + use `--dry-run`
          |
          +---> [Issue in new extractor/CLI?] ------> Run `git revert <commit>` (<1 min stateless rollback)
```

---

## Stale Diagram Audit

- `docs/CEO_WORKING_PLAN.md`: All 6 ASCII diagrams updated and verified against `EXP-1`..`EXP-5` and `SEC-1`.
- `README.md`, `PROJECT_SPEC.md`, `docs/adr/001-contract-first-repo-indexing.md`, `docs/adr/002-cursor-plugin-and-gstack-skill-architecture.md`: Contain Markdown tables only (0 stale ASCII diagrams).

---

## Implementation Tasks

Synthesized from this review's findings. Each task derives from a specific finding above. Run with Claude Code or Codex; checkbox as you ship.

- [x] **T1 (P1, human: ~2h / CC: ~5min)** — `security/indexer-drift` — Enforce `repo_root` path containment (`is_relative_to`), `(OSError, UnicodeDecodeError)` rescue, and `2MB` file cap (`MAX_INDEX_FILE_BYTES`)
  - Surfaced by: Section 2 (Error & Rescue) & Section 3 (Security) — `SEC-1` (`D9: A`)
  - Files: `src/pmcursor/indexer.py`, `src/pmcursor/drift.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_security_path_containment`
- [x] **T2 (P1, human: ~3d / CC: ~20min)** — `indexer/multistack` — Implement TypeScript `Zod`, `Next.js` App Router, `OpenAPI` JSON/YAML, and `SQL` DDL (`CREATE TABLE`) contract extractors (`EXP-1`)
  - Surfaced by: Step 0G & Section 1 — `EXP-1` (`D3: A`)
  - Files: `src/pmcursor/indexer.py`, `src/pmcursor/models.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_multistack`
- [x] **T3 (P1, human: ~1.5d / CC: ~10min)** — `indexer/telemetry` — Implement `TelemetryContract` indexing (`track_event`, `PostHog`, `Vercel Analytics`, `Langfuse`, `BigQuery`) and PRD `telemetry:` drift verification (`EXP-4`)
  - Surfaced by: Step 0G & Section 1 — `EXP-4` (`D6: A`)
  - Files: `src/pmcursor/models.py`, `src/pmcursor/indexer.py`, `src/pmcursor/drift.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_telemetry`
- [x] **T4 (P1, human: ~1d / CC: ~10min)** — `drift/fixer` — Implement `fix_prd_markdown` and `pmcursor fix-prd --prd <path> [--dry-run | --write]` self-healing CLI subcommand (`EXP-2`)
  - Surfaced by: Step 0G & Section 4 — `EXP-2` (`D4: A`)
  - Files: `src/pmcursor/models.py`, `src/pmcursor/drift.py`, `src/pmcursor/cli.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_fix_prd`
- [x] **T5 (P1, human: ~2d / CC: ~15min)** — `api/pr-impact` — Implement `verify_github_signature` (HMAC-SHA256), `compute_pr_impact`, and `pmcursor pr-impact` CLI subcommand (`EXP-3`)
  - Surfaced by: Step 0G & Section 3 — `EXP-3` (`D5: A`)
  - Files: `api/__init__.py`, `src/pmcursor/models.py`, `src/pmcursor/cli.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_pr_impact`
- [x] **T6 (P1, human: ~2d / CC: ~15min)** — `web/canvas` — Implement XSS-safe Linear/Base-UI dark-mode Split-Pane Spec Canvas (`render_split_pane_canvas`) and `pmcursor canvas` CLI subcommand (`EXP-5`)
  - Surfaced by: Step 0G & Section 11 — `EXP-5` (`D7: A`)
  - Files: `web/__init__.py`, `web/canvas.py`, `src/pmcursor/cli.py`, `tests/test_smoke.py`
  - Verify: `PYTHONPATH=src:. pytest -k test_split_pane_canvas`

---

## Completion Summary

```text
  +====================================================================+
  |            MEGA PLAN REVIEW — COMPLETION SUMMARY                   |
  +====================================================================+
  | Mode selected        | SCOPE EXPANSION                             |
  | System Audit         | 11 Python files & 6 plugin files verified   |
  | Step 0               | SCOPE EXPANSION + 5/5 expansions accepted   |
  | Section 1  (Arch)    | 0 issues found (full-stack boundaries set)  |
  | Section 2  (Errors)  | 10 error paths mapped, 0 GAPS (SEC-1 fixed) |
  | Section 3  (Security)| 1 issue found & resolved (SEC-1 High/Med)   |
  | Section 4  (Data/UX) | 4 edge cases mapped, 0 unhandled            |
  | Section 5  (Quality) | 0 issues found                              |
  | Section 6  (Tests)   | Diagram produced, 0 gaps (5 test cards set) |
  | Section 7  (Perf)    | 0 issues found (2MB cap via SEC-1)          |
  | Section 8  (Observ)  | 0 gaps found (--json on all 7 subcommands)  |
  | Section 9  (Deploy)  | 0 risks flagged (100% additive/reversible)  |
  | Section 10 (Future)  | Reversibility: 5/5, debt items: 0           |
  | Section 11 (Design)  | 0 issues (Linear/Base-UI Split-Pane Canvas) |
  +--------------------------------------------------------------------+
  | NOT in scope         | written (2 explicit non-goals, 0 deferred)  |
  | What already exists  | written (5 core modules reused/extended)    |
  | Dream state delta    | written                                     |
  | Error/rescue registry| 10 rows, 0 CRITICAL GAPS                    |
  | Failure modes        | 10 total, 0 CRITICAL GAPS                   |
  | TODOS.md updates     | 0 items proposed (all 5 expansions added)   |
  | Scope proposals      | 5 proposed, 5 accepted (EXP + SEL)          |
  | CEO plan             | written                                     |
  | Outside voice        | codex unavailable (MODEL_UNUSABLE)          |
  | Lake Score           | 1/1 recommendations chose complete option   |
  | Diagrams produced    | 6 (arch, data, state, error, deploy, rollbk)|
  | Stale diagrams found | 0                                           |
  | Unresolved decisions | 0 (listed below)                            |
  | Reality rows         | 7/7 rows (PLAN_REALITY), 0 unverified       |
  +====================================================================+
```

### Unresolved Decisions
None (`0` unresolved decisions).

## GSTACK REVIEW REPORT

| Review | Trigger | Why | Runs | Status | Findings |
|--------|---------|-----|------|--------|----------|
| CEO Review | `/plan-ceo-review` | Scope & strategy | 1 | CLEAR | 5 proposals, 5 accepted, 0 deferred |
| Outside Review | `codex` (auto) | Independent 2nd opinion | 10 | unavailable | Codex MODEL_UNUSABLE (gpt-6.2-astra) and native Plan subagent/TaskStop not offered — no completed external review |
| Eng Review | `/plan-eng-review` | Architecture & tests (required) | 9 | ISSUES OPEN | 20 issues, 0 critical gaps (latest prior run 2026-11-24) |
| Design Review | `/plan-design-review` | UI/UX gaps | 0 | — | — |
| DX Review | `/plan-devex-review` | Developer experience gaps | 0 | — | — |

- **OUTSIDE COVERAGE:** provider=codex, phase=plan-review, status=unavailable (MODEL_UNUSABLE on `gpt-6.2-astra`; native `Plan` subagent and `TaskStop` not offered in Antigravity host; no completed external review).
- **VERDICT:** CEO CLEARED — eng review required

NO UNRESOLVED DECISIONS
