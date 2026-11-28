# Diagnostics (`pmcursor doctor`)

## Sub-features

- Report environment health: Python version, `pmcursor[server]` extra
  availability, plugin manifest validity, and which API token / webhook
  secrets are configured.
- `--json` emits the diagnostic report.

## How to get to it (user POV)

First step of any verification run (the Doctor step in `../SKILL.md`) —
confirms the venv can serve and the plugin is intact before driving
anything.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor doctor --repo . --json
echo $?   # expect 0
```

Proof of working: report has `python_version`, `server_extra_available`,
`plugin_valid`, `api_token_configured`, and the three webhook-secret flags
(`github`, `linear`, `jira`). Verified: py3.11.7, server extra available,
plugin valid, no secrets configured — all `false` flags are correct for a
local venv with no env set.

## Gotchas

- All secret flags read env vars only — they are `false` in a fresh shell,
  not a misconfiguration.
- `server_extra_available: false` means `pmcursor[server]` is not installed;
  fix with `uv pip install -e '.[server]'` before any `serve` proof.
