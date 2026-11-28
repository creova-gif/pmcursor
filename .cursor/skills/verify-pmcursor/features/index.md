# Repository indexing

## Sub-features

- Index Pydantic models, FastAPI routes, ADRs, telemetry contracts, Zod schemas,
  Next.js routes, OpenAPI specs, SQL DDL, Prisma, and GraphQL into one `RepoMap`.
- Emit the map to stdout (`--json`) or to a file (`--output repo_map.json`).
- Path containment: files outside `--repo` are never read; files over 2MB are
  skipped (`SEC-1` guard).

## How to get to it (user POV)

A PM or agent runs `pmcursor index --repo . --json` in a terminal at the root of
the repository they want indexed. There is no UI; the RepoMap is the input to
`drift`, `checklist`, and `canvas`.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor index --repo . --json > repo_map.json
echo $?   # expect 0
```

Proof of working: `repo_map.json` parses as JSON and contains
`repo_root` equal to the absolute repo path, `indexed_files > 0`, and non-empty
`models` / `routes` / `adrs` lists. On this checkout expect roughly
`models: 37`, `routes: 16`, `adrs: 3`, `indexed_files: ~96` (counts drift as
code changes; `> 0` is the real assertion).

## Gotchas

- `--json` writes the map to stdout; without it the map prints a summary.
  Capture stderr separately — warnings about skipped files go there.
- `telemetry` is `0` on this repo today (no `track_event` call sites); a zero
  count is correct behavior, not a bug.
- Indexing this repo takes ~1s cold. In the API server the result is cached in
  memory (`RepoIndexCache`) — the CLI itself has no cache, each run re-indexes.
- Pointing `--repo` at a non-existent path exits non-zero with an error on
  stderr — that failure IS the correct behavior to capture.
