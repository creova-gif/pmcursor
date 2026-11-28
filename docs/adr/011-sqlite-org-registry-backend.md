# ADR-011: SQLite org-registry backend for multi-writer deployments

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
ADR-006's file-backed `OrgRegistry` writes the entire org store on every mutation via tempfile + `os.replace` — correct and atomic, but **single-writer**: two writer processes (uvicorn workers, concurrent CLI invocations) race last-writer-wins and silently lose each other's orgs, keys, and root grants. M25 documented `WEB_CONCURRENCY=1` as a hard requirement and `run_server` refuses to start multi-worker while the file backend is configured — meaning org-keyed deployments had no supported path to more than one worker per node. Additionally, `resolve_key` scans every org's keys on each request (O(orgs × keys)); the file backend is correct for single-node but has no horizontal headroom.

## Decision
`SQLiteOrgRegistry` (stdlib `sqlite3`, zero new dependencies) implements the same `OrgStore` protocol as `OrgRegistry`:

- **Schema:** `orgs` / `org_keys` / `org_roots` tables; key ids are primary keys so `resolve_key` is an indexed lookup instead of a scan.
- **Multi-writer safe:** `PRAGMA journal_mode=WAL` + `busy_timeout=5000`; multi-statement mutations (`create_org`) run in a single `BEGIN IMMEDIATE` transaction, single-statement mutations are autocommitted atomically, and reads take the intra-process lock.
- **Semantics parity:** same `pmk_` issuance, `hmac.compare_digest` resolution, `last_used_at` metering, audit events (`org_created`, `org_key_issued`, `org_key_revoked`, `org_roots_updated`), same `Org`/`OrgApiKey` models, same error contract (`OrgRegistryError`). A parity test asserts both backends produce identical org state.
- **Selection:** `PMCURSOR_ORG_BACKEND=file|sqlite` (default `file`) via `org_registry_for_path`; `pmcursor orgs --backend sqlite` for admin operations.
- **`run_server`** only refuses `WEB_CONCURRENCY>1` for the file backend — `sqlite` is the supported multi-worker path.
- **`verify()`** runs `PRAGMA quick_check` so `/readyz` reports degraded on corruption, same contract as the file backend.

The file backend remains the default and is not deprecated: it needs no schema, is diffable in version control, and suits the dominant single-node deployment shape. `OrgStore` is a `Protocol`, so a future Postgres backend can implement it without touching callers.

## Alternatives considered
- **Postgres/MySQL backend now:** the right long-term answer for the accounts layer, but adds an infrastructure dependency (server, driver, migrations) the product can't justify pre-launch — sqlite3 is stdlib and ships in the same container.
- **File locking (fcntl) around the JSON store:** cross-platform hazard (no fcntl on Windows, advisory locks don't compose with `os.replace` cleanly) and still O(full-store) per write.
- **Keep single-writer + document:** the status quo; rejected because it leaves an operability cliff (no multi-worker path) documented as a residual risk.

## Consequences
- **Positive:** multi-worker and multi-CLI deployments are supported; key resolution is indexed; `/readyz` probes integrity; the residual-risk entry shrinks to "sqlite is single-node too — a real DB belongs to the accounts layer."
- **Negative:** two backends to keep semantically aligned — mitigated by the `OrgStore` protocol, shared `_resolve_org_id`/`_new_key_record` helpers, and the parity test.
- **Follow-ups:** migration path file→sqlite (`orgs` CLI or one-shot script) if a deployment outgrows the file backend; Postgres backend when the accounts layer lands.
