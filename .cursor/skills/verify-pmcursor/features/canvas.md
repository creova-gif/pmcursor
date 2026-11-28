# Split-pane spec canvas

## Sub-features

- Render an interactive HTML page (`render_split_pane_canvas`) that pairs the
  PRD markdown with the indexed contracts — a spec inspector, not a live app.
- Optional `EdgeCaseChecklist` pane when checklist data is included.
- WCAG 2.1 AA canvas (landmarks, keyboard-navigable panes) and a responsive
  mobile layout via `@media (max-width: 900px)` — both regression-tested in
  `tests/test_canvas_accessibility.py` and `tests/test_canvas_responsive.py`.
- `POST /v1/canvas` returns the same page as `HTMLResponse`.

## How to get to it (user POV)

A PM runs `pmcursor canvas --prd PROJECT_SPEC.md --repo . --output canvas.html`
and opens the file in a browser to walk spec-vs-code side by side, or shares it
with a reviewer. There is no server — the artifact is the product.

## Driving it with the pmcursor CLI + curl

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor canvas --prd PROJECT_SPEC.md --repo . --output canvas.html
echo $?   # expect 0
```

Proof of working: `canvas.html` exists (expect ~50KB on this checkout), is
self-contained HTML, contains the spec text (e.g. `grep -c "PROJECT_SPEC\|pmcursor" canvas.html > 0`),
the responsive media query (`grep '@media (max-width: 900px)' canvas.html`),
and ARIA landmarks (`grep -o 'role="[a-z]*"' canvas.html | sort -u`).
Checklist fields must be HTML-escaped — `grep -c '&lt;' canvas.html` should be
non-zero when code samples appear.

Via the API:

```bash
curl -sf -X POST http://127.0.0.1:8123/v1/canvas \
  -H 'Content-Type: application/json' \
  -d "$(python3 - <<'PY'
import json
print(json.dumps({
    "prd_markdown": open("PROJECT_SPEC.md").read(),
    "repo_root": ".",
    "prd_path": "PROJECT_SPEC.md",
}))
PY
)" -o canvas-api.html
```

`canvas-api.html` is the same page served with `text/html` content type.

## Gotchas

- The HTML is static — assertions on markup are the proof. Only open it in a
  browser if the task is about *rendering*; for markup checks, greps are
  deterministic and faster.
- `--output` chooses where the file lands; copy it into
  `.pmcursor-verify/evidence/<run-id>/` before teardown — it is the artifact.
- Escaping matters: raw `<` from code snippets must appear as `&lt;` in the
  output. A finding of unescaped HTML in user content is a real XSS bug —
  report it, do not paper over it.
- No selector-driven harness is configured for this repo; if visual proof is
  required, open the file with `open canvas.html` (macOS) and capture a
  screenshot separately — there is no bundled Playwright spec.
