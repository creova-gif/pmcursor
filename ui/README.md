# PMCursor UI

Interactive split-pane workspace for PMCursor — a Next.js app that replaces the
static `web/canvas.py` HTML render with a live client over the FastAPI backend.

## Layout

- **Left pane — Living PRD:** the PRD markdown (editable), alignment-score
  strip, drift findings sorted by severity, and the generated edge-case
  checklist.
- **Right pane — Repository Contracts:** indexed `RepoMap` — models with
  fields, routes, telemetry events, and ADRs, each with `file:line` citations.

## Running

1. Start the API (requires `pmcursor[server]`):

   ```bash
   PYTHONPATH=src pmcursor serve --port 8000
   ```

2. Start the UI:

   ```bash
   cd ui
   npm install
   PMCURSOR_API_URL=http://localhost:8000 npm run dev
   ```

3. Open http://localhost:3000, set the repo root and PRD path, paste or edit
   the PRD markdown, and run a drift audit.

## Configuration

| Env var               | Default                 | Purpose                                   |
| --------------------- | ----------------------- | ----------------------------------------- |
| `PMCURSOR_API_URL`    | `http://localhost:8000` | Base URL of `pmcursor serve`              |
| `PMCURSOR_API_TOKEN`  | —                       | Bearer token injected by the proxy route  |

The browser never talks to the Python API directly: `app/api/pmcursor/[...path]`
proxies `/api/pmcursor/<endpoint>` → `${PMCURSOR_API_URL}/v1/<endpoint>`,
injecting `PMCURSOR_API_TOKEN` server-side so no CORS setup is required.
