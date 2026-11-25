# PMCursor Engineering Review Report (`T1`–`T6`: `EXP-1`..`EXP-5` & `SEC-1`)

**Date:** 2026-11-25  
**Scope:** `src/pmcursor/models.py`, `src/pmcursor/indexer.py`, `src/pmcursor/drift.py`, `src/pmcursor/cli.py`, `api/__init__.py`, `web/canvas.py`, and `tests/test_smoke.py`

---

## 1. Architecture & Dependency Layering

The codebase follows a clean, acyclic dependency graph with zero circular imports:

- **`src/pmcursor/models.py`**: Pure Pydantic v2 data contracts with `model_config = ConfigDict(frozen=True)` across all 14 contract/report models (`FieldContract`, `ModelContract`, `RouteContract`, `TelemetryContract`, `ADRContract`, `RepoMap`, `DriftFinding`, `SpecAlignmentScore`, `DriftReport`, `FixPrdResult`, `PRImpactItem`, `PRImpactReport`, `PluginValidationResult`, `EvalBenchmarkResult`). Imports only stdlib (`typing.Literal`) and `pydantic`.
- **`src/pmcursor/indexer.py` & `src/pmcursor/drift.py`**: Depend exclusively on `pmcursor.models` and Python stdlib (`ast`, `json`, `re`, `pathlib`).
- **`web/canvas.py`**: Depends exclusively on `pmcursor.models` and stdlib `html`.
- **`api/__init__.py`**: Composes `pmcursor.models`, `pmcursor.indexer`, and `pmcursor.drift` (plus `pydantic.BaseModel` for `DriftAuditRequest` and `GitHubWebhookPayload`).
- **`src/pmcursor/cli.py`**: Top-level CLI entrypoint wiring `pmcursor.{drift,eval_runner,indexer,plugin_validator}`, `api`, and `web.canvas`.

**Observations (Low):**
- `api/` and `web/` reside at the repository root rather than under `src/pmcursor/`. `pyproject.toml` configures `pythonpath = ["src", "."]` for `pytest`, so running `python3 -m pmcursor.cli` outside `pytest` requires `PYTHONPATH=src:.` (or an editable install covering `api` and `web`).

---

## 2. Error & Rescue Paths

All file-system and parser boundaries in the indexing and drift engines handle failure modes explicitly without bare `except Exception: pass`:

- **Size cap (`MAX_INDEX_FILE_BYTES = 2_097_152`)**: `index_repository` checks `path.stat().st_size > MAX_INDEX_FILE_BYTES` inside `try ... except OSError: continue` (`src/pmcursor/indexer.py:1029-1033`), skipping oversized files (verified by `huge.ts` in `test_security_path_containment_and_binary_resilience`).
- **Python AST parsing**: Wraps `read_text(encoding="utf-8")` and `ast.parse(...)` in `except (OSError, UnicodeDecodeError, SyntaxError): continue` (`src/pmcursor/indexer.py:1040-1044`).
- **TypeScript / SQL / ADR / OpenAPI parsing**: Wraps file reads in `except (OSError, UnicodeDecodeError)` and JSON parsing in `except json.JSONDecodeError` (`src/pmcursor/indexer.py:771-790, 981-984, 1049-1065`).
- **Drift citation verification & self-healing**: `_verify_citations` and `fix_prd_markdown` wrap `candidate.read_text(encoding="utf-8")` in `except (OSError, UnicodeDecodeError)` (`src/pmcursor/drift.py:120-123, 582-585`).
- **Git diff subprocess**: `_load_diff_text` runs `git diff` with `check=False` and returns `""` on non-zero exit (`src/pmcursor/cli.py:258-269`).

**Observations (Low):**
- `cli.py` reads user-specified `--prd` and `--diff` files directly without catching `OSError`/`UnicodeDecodeError` (acceptable for local CLI invocations, though a friendly stderr message could be added later).

---

## 3. Security Review (`SEC-1`)

- **Constant-time GitHub webhook verification (`api/__init__.py:48-56`)**: `verify_github_signature` rejects empty secrets and headers missing the `sha256=` prefix, computes `hmac.new(secret.encode("utf-8"), payload_body, hashlib.sha256).hexdigest()`, and compares via `hmac.compare_digest`. `handle_github_webhook` enforces signature verification *before* JSON deserialization, raising `PermissionError` on mismatch (`api/__init__.py:236-238`).
- **XSS protection in split-pane HTML canvas (`web/canvas.py`)**: All dynamic values (`report.prd_path`, `report.status`, `finding.*`, `model.*`, `route.*`, `telemetry.*`, `adr.*`, `prd_md`, and `data-search` attributes) pass through `_esc()` (`html.escape(value, quote=True)`). Status and severity colors are resolved from fixed literal-keyed dictionaries (`_STATUS_COLORS`, `_SEVERITY_COLORS`) with a static fallback (`#9494a0`).
- **Path traversal containment (`src/pmcursor/drift.py:91-103, 579-581`)**: Both `_verify_citations` and `fix_prd_markdown` resolve `(root / rel_path).resolve()` and enforce `candidate.is_relative_to(resolved_root)`. Escaping paths are flagged as `critical` `fabricated_citation` findings in `check_spec_drift` and skipped in `fix_prd_markdown`.

**Defense-in-Depth Note (Low):**
- `handle_github_webhook` passes `payload.repo_root` from the signed webhook JSON into `Path(payload.repo_root).resolve()` and `index_repository(root)`. Because the payload is HMAC-authenticated, this is safe for trusted CI/webhook callers; if exposed in a multi-tenant service, `repo_root` should be constrained to an allowlisted workspace base directory.

---

## 4. Test Coverage & Static Analysis

Executed after final implementation:

- **`pytest -v`**: **10 passed in 0.53s** (`tests/test_smoke.py` — all 10 tests covering healthcheck, plugin manifest validation, deterministic eval benchmark with `recall == 1.0` and `0` unflagged fabricated citations, Python/FastAPI/ADR indexing, multi-stack Zod/Next.js/SQL/OpenAPI/PostHog indexing, `fix-prd` dry-run/write/idempotency, PR impact & webhook HMAC verification, split-pane canvas & XSS escaping, binary/size resilience & path containment, and CLI commands).
- **`mypy --strict src api web tests`**: **Success: no issues found in 11 source files**.
- **`ruff check .`**: Not run (`ruff` binary not installed in this environment).

**Minor Coverage Notes (Low):**
- `handle_github_webhook` rejection (`PermissionError` on bad signature), OpenAPI YAML (`_parse_simple_yaml`), and TypeScript `interface` extraction are not directly exercised by dedicated unit tests in `tests/test_smoke.py`.

---

## 5. Performance & Edge Cases

- **Linear-time scanning**: `_find_matching_delimiter` and `_split_top_level_with_offsets` in `src/pmcursor/indexer.py` perform single-pass quote/escape-aware scanning without nested backtracking regexes.
- **Directory pruning & file cap**: `IGNORED_DIRS` and hidden-directory filtering (`part.startswith(".")`) avoid traversing `.git`, `node_modules`, `.venv`, and build artifacts; `MAX_INDEX_FILE_BYTES` bounds memory usage.
- **Zero-line deletion hunks**: `parse_unified_diff_ranges` (`api/__init__.py:79`) computes `end_line = max(start_line, start_line + count - 1)`, ensuring `count=0` deletion hunks still match contract lines.

---

## GSTACK REVIEW REPORT

- **Status:** 10/10 pytest tests passing; `mypy --strict` clean across 11 source files (`ruff` unavailable in environment).
- **Critical / High Gaps:** 0
- **Low / Defense-in-Depth Notes:** Root-level `api/` and `web/` packaging path (`PYTHONPATH=src:.`), `handle_github_webhook` `repo_root` allowlist in multi-tenant deployments, and minor unit test additions (negative webhook test, YAML OpenAPI, TS `interface`).
- **VERDICT: ENG CLEARED**
