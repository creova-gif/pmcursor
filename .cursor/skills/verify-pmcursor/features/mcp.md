# MCP server (`pmcursor mcp`)

## Sub-features

- Run the stdio MCP server exposing PMCursor tools to MCP clients (Cursor,
  Claude Desktop): `pmcursor_index`, `pmcursor_drift`, `pmcursor_checklist`,
  `pmcursor_ticket_sync`, `pmcursor_release_notes`, `pmcursor_flags`,
  `pmcursor_telemetry_verify`.
- Wire format: line-delimited JSON-RPC 2.0 (one message per line, no
  Content-Length framing).
- `--workspace-root` confines tool `repo_root` arguments to a directory.

## How to get to it (user POV)

An agent user registers `pmcursor mcp` in `.mcp.json` so their IDE can call
the indexer and drift engine as tools — see `.mcp.json` at the repo root.
There is no CLI REPL; it speaks MCP over stdin/stdout.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
printf '%s\n%s\n%s\n' \
  '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2024-11-05","capabilities":{},"clientInfo":{"name":"verify","version":"1"}}}' \
  '{"jsonrpc":"2.0","method":"notifications/initialized"}' \
  '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}' \
| PYTHONPATH=src .venv/bin/python -m pmcursor.cli mcp --workspace-root .
echo $?   # expect 0
```

Proof of working: two responses on stdout (the `initialized` notification
gets none). `id:1` returns `serverInfo {name: "pmcursor", version}` +
`protocolVersion "2024-11-05"`; `id:2` returns the seven `pmcursor_*` tools.
Verified: version `0.2.0`, 7 tools listed.

## Gotchas

- The flag is `--workspace-root`, NOT `--repo` — `--repo` is rejected
  (exit 2).
- Notifications (no `id`) produce no response line — count responses, not
  input lines.
- Each JSON-RPC message is exactly one line of compact JSON; pretty-printed
  multi-line JSON is not valid input.
