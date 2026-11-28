# Edge-case checklist

## Sub-features

- Generate a codebase-cited edge-case checklist: for every indexed model field
  and route, an item naming the concrete edge case (omitted required field,
  null optional, invalid type) with its `file:line` citation.
- Priorities `P0`/`P1`/`P2` and categories like `schema_validation`.
- `--output` writes Markdown; `POST /v1/checklist` returns the
  `EdgeCaseChecklist` model as JSON.

## How to get to it (user POV)

A PM about to scope a release runs
`pmcursor checklist --repo . --prd PROJECT_SPEC.md --output checklist.md` to get
a reviewable list of edge cases grounded in the actual code, not guessed. The
file goes into a PR or Linear ticket.

## Driving it with the pmcursor CLI + curl

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor checklist --repo . --prd PROJECT_SPEC.md --output checklist.md
echo $?   # expect 0
```

Proof of working: `checklist.md` exists, starts with
`## PMCursor Edge-Case Checklist`, reports `Total items: N` in its header, and
every item cites a real path like `api/__init__.py:26`. On this checkout expect
~128 items. Assert a citation resolves:
`grep -o 'api/__init__.py:[0-9]*' checklist.md | head -1`.

Via the API:

```bash
curl -sf -X POST http://127.0.0.1:8123/v1/checklist \
  -H 'Content-Type: application/json' \
  -d '{"repo_root": ".", "prd_markdown": null}' > checklist.json
```

Proof: JSON has `items` array; each item carries `file_path`/`line` style
citations matching the schema in `src/pmcursor/checklists.py`.

## Gotchas

- `--output` is required to get the Markdown artifact — without it the report
  prints to stdout and nothing lands on disk. Capture which you used.
- `prd_markdown` is optional in `ChecklistRequest`; omitting it yields a
  checklist driven purely by the repo index. Pass the real spec to prove the
  PRD-aware path.
- Item citations point at API request models and indexed models — spot-check
  one with `sed -n '<line>p' <file>`; a citation to a line that doesn't contain
  the named field is a real finding to report, not to normalize away.
