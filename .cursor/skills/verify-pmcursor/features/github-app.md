# GitHub App management (`pmcursor github-app`)

## Sub-features

- `manifest`: emit the GitHub App manifest JSON to paste into
  github.com/settings/apps/new — names the app, sets `webhook-url`,
  permissions (`contents:read`, `pull_requests:write`, `issues:write`,
  `checks:write`, `merge_queues:read`) and events
  (`pull_request`, `push`, `merge_group`, `check_run`).
- `convert`: exchange the manifest-creation redirect `code` for app
  credentials (requires network + `--code`).
- `token`: mint an installation token (requires `pmcursor[github-app]` +
  `PMCURSOR_GITHUB_APP_ID` + private key env).

## How to get to it (user POV)

To install PMCursor as a GitHub App, a maintainer runs
`pmcursor github-app manifest --webhook-url <deployed>/v1/webhooks/github`,
pastes the JSON into GitHub, then uses `convert` and `token` to complete the
flow. `GET /v1/github-app/manifest` is the API twin.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor github-app manifest \
  --webhook-url https://pm.example.com/v1/webhooks/github --json
echo $?   # expect 0
```

Proof of working: manifest JSON has `name: "pmcursor-drift"`,
`hook_attributes.url` matching `--webhook-url`, `default_permissions` with
`contents:read`/`pull_requests:write`, and `default_events`. Verified
offline — `manifest` is the only credential-free action.

## Gotchas

- Only `manifest` runs offline; `convert` and `token` need real GitHub
  credentials and network — capture their auth error as the failure proof.
- `--webhook-url` is written verbatim into `hook_attributes.url` — it must
  be the deployed server's public URL, not localhost.
- `convert`/`token` need `PMCURSOR_GITHUB_APP_ID` +
  `PMCURSOR_GITHUB_APP_PRIVATE_KEY`/`_PATH` and `pmcursor[github-app]`
  (PyJWT) installed.
