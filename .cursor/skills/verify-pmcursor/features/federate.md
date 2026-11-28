# Multi-repo federation (`pmcursor federate`)

## Sub-features

- Index several repositories under `alias=path` prefixes and merge them into
  one `RepoMap` with alias-prefixed contract names.
- With `--prd`, run drift checks against the federated map.

## How to get to it (user POV)

A PM on a monorepo-adjacent setup (separate backend + frontend repos) runs
`pmcursor federate --repos api=./backend web=./frontend` to get one merged
contract map instead of auditing each repo in isolation.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor federate --repos main=. --json > federated.json
echo $?   # expect 0
```

Proof of working: `federated.json` is a merged `RepoMap`; contract names are
prefixed by alias (e.g. `main:`). Verified with a single `main=.` entry —
produced a full map (~65KB). Real use passes 2+ repos.

## Gotchas

- Each `--repos` entry must be `alias=path` — a bare path errors.
- Aliases must be unique; duplicate aliases collide in the merged map.
- With one repo the output is just that repo's map with a `main:` prefix —
  useful for shape verification, less useful as a federation proof.
