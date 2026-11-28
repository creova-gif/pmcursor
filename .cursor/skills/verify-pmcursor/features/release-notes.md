# Release notes (`pmcursor release-notes`)

## Sub-features

- Synthesize diff-grounded release notes + a PRD-to-repo `ScopeCoverageReport`
  from `git diff <base>...HEAD` or `--diff-file`.
- `--version` labels the release (default `Unreleased`); `--output` writes the
  markdown to a file.
- `--json` emits `ReleaseNotesReport`.

## How to get to it (user POV)

At release time a PM runs `pmcursor release-notes --prd PROJECT_SPEC.md
--repo . --base v0.1.0 --version v0.2.0` to get notes tied to what actually
changed, plus how much of the spec the diff covers.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor release-notes --prd PROJECT_SPEC.md --repo . \
  --base v0.1.0 --version v0.2.0 --json > notes.json
echo $?   # expect 0
```

Proof of working: `ReleaseNotesReport` carries a `version` echo and a
diff-grounded notes body; verified against `v0.1.0..HEAD` (~31KB report).
The `ScopeCoverageReport` quantifies PRD-to-repo scope coverage.

## Gotchas

- `--base` defaults to `HEAD~1` — for a real release pass the previous tag.
- Requires `--prd`; the coverage matrix is meaningless without the spec.
- An unchanged diff yields empty notes — correct, not an error.
