---
name: verify-pmcursor
description: Drive the real PMCursor app (pmcursor CLI and the FastAPI service from `pmcursor serve`) to prove behavior end-to-end and capture evidence. Reach for this when you need to verify a change works, reproduce a reported bug, or audit a user-facing feature in this repo — not for unit tests, which live in `tests/`.
---

# verify-pmcursor

PMCursor has four user-facing surfaces. Pick the one the task is about; most proofs
use the CLI or the API.

| Surface | What the user touches | How to drive |
|---|---|---|
| `pmcursor` CLI | Terminal: `index`, `drift`, `fix-prd`, `checklist`, `canvas`, `release-notes`, `flags`, `federate`, `telemetry-verify`, `dashboard`, `ticket-sync`, `pr-impact`, `publish`, `doctor`, `validate-plugin`, `eval` | Direct subprocess. Capture stdout, stderr, exit code. |
| FastAPI service | HTTP API started by `pmcursor serve` — endpoints under `/v1/*`, probes `/health`, `/readyz`, `/metrics` | `curl` against `127.0.0.1` on a verification port you own. |
| Canvas report | Interactive HTML file produced by `pmcursor canvas` or `POST /v1/canvas` | Assert on the generated HTML (tags, escaped fields, layout markers). Open in a browser only if the task demands visual proof. |
| MCP stdio server | `pmcursor mcp` — JSON-RPC over stdin/stdout for IDE agents | Pipe JSON-RPC lines into the process's stdin, read responses on stdout. |

The repo itself is the test subject: `PROJECT_SPEC.md` is a real PRD and the
checkout is a real codebase to index. You never need fixture code to drive the
primary paths.

## Launch

The CLI needs no launch — it is installed in the project venv:

```bash
# from the repo root
.venv/bin/pmcursor doctor
```

If `doctor` reports `server_extra_available : unavailable`, the venv predates the
server extra — reinstall once:

```bash
VIRTUAL_ENV=.venv uv pip install -e '.[server]'   # uv is at ~/.local/bin/uv if not on PATH
```

For the API surface, start a verification instance on a port you own
(`8123` is the convention; any free port works — the default `8000` may belong
to the user's dev session, so never reuse it):

```bash
.cursor/skills/verify-pmcursor/helpers/up.sh 8123
```

`up.sh` backgrounds `pmcursor serve --host 127.0.0.1 --port 8123`, polls
`GET /readyz` until it answers `{"status":"ready",...}`, then prints the PID.
Ready means `/readyz` answers — uvicorn logs `Application startup complete`
slightly earlier; do not rely on the log line alone.

State for the run lives under `.pmcursor-verify/` (gitignored):

- `.pmcursor-verify/run/` — scratch: `server.pid`, `server.port`, `server.log`. Removed by teardown.
- `.pmcursor-verify/evidence/<run-id>/` — proof artifacts. Survives teardown; never delete here.

Teardown: `.cursor/skills/verify-pmcursor/helpers/down.sh`. It kills only the
PID it recorded — never `pkill` by process name, you could kill the user's own
server.

## Doctor

Run this first whenever anything looks off. All checks are read-only.

```bash
# 1. CLI works and reports on this environment
.venv/bin/pmcursor doctor          # expect: server_extra_available : available

# 2. The verification port is owned by our run, not someone else's
cat .pmcursor-verify/run/server.pid 2>/dev/null \
  && ps -p "$(cat .pmcursor-verify/run/server.pid)" -o pid,command

# 3. The service answers and it is ours
curl -sf http://127.0.0.1:"$(cat .pmcursor-verify/run/server.port 2>/dev/null || echo 8123)"/health
# expect: {"status":"ok"}
```

Interpretation: `pmcursor doctor` failing means a broken venv — fix install
before driving anything. A PID file whose process is gone, or a port that
answers but with no matching PID file, means a stale or foreign instance —
do not drive it; run `down.sh` and start fresh.

## Drive

Real selectors and commands from this repo — no placeholders.

**CLI.** Invoke `.venv/bin/pmcursor <subcommand>` from the repo root. Every
subcommand exits non-zero on failure; `--json` gives machine-readable output on
most, `--md` human output on `drift`. Key flags:

```bash
.venv/bin/pmcursor index --repo . --json                     # RepoMap on stdout
.venv/bin/pmcursor drift --prd PROJECT_SPEC.md --repo . --json
.venv/bin/pmcursor drift --prd PROJECT_SPEC.md --repo . --json --fail-on-drift  # exit 1 on findings
.venv/bin/pmcursor checklist --repo . --prd PROJECT_SPEC.md --output checklist.md
.venv/bin/pmcursor canvas --prd PROJECT_SPEC.md --repo . --output canvas.html
.venv/bin/pmcursor dashboard --repo . --json
```

**API.** POST JSON to the running instance. `repo_root` is resolved relative to
the server process's cwd — launch `up.sh` from the repo root so `"."` means this
repo, or pass an absolute path.

```bash
curl -sf -X POST http://127.0.0.1:8123/v1/drift/audit \
  -H 'Content-Type: application/json' \
  -d "$(python3 - <<'PY'
import json
print(json.dumps({
    "prd_markdown": open("PROJECT_SPEC.md").read(),
    "repo_root": ".",
    "prd_path": "PROJECT_SPEC.md",
}))
PY
)"
```

The `DriftAuditRequest` schema is `api/__init__.py:25` — `prd_markdown`
(required), `repo_root`, `prd_path`. Other POST bodies live beside it
(`ChecklistRequest`, `CanvasRequest`, `FlagAuditRequest`, ...).

Auth: with `PMCURSOR_API_TOKEN` unset (the dev default), loopback requests need
no header. To verify auth itself, start with `PMCURSOR_API_TOKEN=test-token`
and expect `401` without a header, `200` with
`-H 'X-PMCursor-Token: test-token'` or `-H 'Authorization: Bearer test-token'`.

**MCP.** `printf` a JSON-RPC line into `.venv/bin/pmcursor mcp`, e.g. an
`initialize` request followed by `tools/list`. Stdio only — there is no socket.

## Evidence

Put every proof artifact in `.pmcursor-verify/evidence/<run-id>/` where
`<run-id>` is a timestamp (`date +%Y%m%d-%H%M%S`) or the task slug. Capture:

- The command and its full stdout/stderr (`cmd > out.txt 2> err.txt; echo $? > exit.txt`).
- Response bodies (`curl -o drift-response.json`), not just status codes.
- Generated files (`canvas.html`, `checklist.md`) — copy them into evidence before teardown.
- Server log tail (`cp .pmcursor-verify/run/server.log`) when the API is involved.
- Side effects: `/readyz` `cached_repos` climbing after an audit proves the index cache engaged; `--fail-on-drift` exit code proves the gate.

Proof standards:

- Exercise the real user path — the actual CLI subcommand or the actual REST
  endpoint. Do not call `pmcursor.drift.check_spec_drift` from a Python REPL and
  claim the CLI works.
- Capture the action *and* the resulting state: the request plus the response,
  the command plus the file it wrote.
- Mocks are acceptable only at real external boundaries — GitHub/Linear/Jira
  comment publishing (`publish`, `/v1/publish`) and webhook signature
  verification use secrets you do not have; stop at the local validation error
  or use unsigned/self-signed requests to prove the guard, not the delivery.
- `fix-prd --dry-run` and similar flags: verify what they actually skip by
  checking the filesystem and git state before/after, not by trusting the name.

## Cleanup

```bash
.cursor/skills/verify-pmcursor/helpers/down.sh
```

Kills the recorded PID, waits for the port to free, removes
`.pmcursor-verify/run/` (pid, port, log). Leaves `evidence/` untouched —
confirm your artifacts are still there after teardown. If a run dies
mid-proof, run `down.sh` anyway so the port and process are not stranded.

## Isolation

- CLI invocations are stateless — any number can run concurrently.
- Each server instance needs its own port and its own
  `.pmcursor-verify/run/` — do not run two `up.sh` sessions in the same
  checkout; use a second checkout or serialize. Port `8000` is the documented
  default and may belong to the user — never drive or kill it.
- The server caches indexes in memory (`RepoIndexCache`); nothing persists to
  disk, so a fresh process is a clean slate. `POST /v1/cache/clear` resets it
  without a restart.

## Helpers

Both live in `.cursor/skills/verify-pmcursor/helpers/` and are executable.
Run them from the repo root.

- `./up.sh [port]` — start the API on the given port (default `8123`), wait for
  `/readyz`, write `.pmcursor-verify/run/{server.pid,server.port,server.log}`,
  print `READY pid=<n> port=<p>`. Fails fast if a run is already recorded.
- `./down.sh` — stop the recorded instance and remove `.pmcursor-verify/run/`.
  Safe to run when nothing is up; prints `nothing to stop`.
