# Plugin manifest validation (`pmcursor validate-plugin`)

## Sub-features

- Validate `.cursor-plugin/plugin.json` and `.claude-plugin/plugin.json`:
  declared components (skills/agents/rules) must exist on disk.
- `--json` emits the validation result.

## How to get to it (user POV)

A contributor editing the plugin packaging runs this before commit to catch a
manifest pointing at a renamed or deleted skill file. CI runs it in
`release.yml`.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor validate-plugin --repo . --json
echo $?   # expect 0
```

Proof of working: `valid: true`, `plugin_name: "pmcursor"`, `version` matches
`pyproject.toml`, `errors: []`, `checked_components` lists every declared
skill/agent/rule file. Verified: version `0.2.0`, 6 components checked.

## Gotchas

- `--repo` must contain `.cursor-plugin/plugin.json`; a repo without it
  errors, not a clean pass.
- The manifest `version` must equal `pyproject.toml` version —
  `tests/test_release_consistency.py` enforces this and fails the release
  workflow on drift.
