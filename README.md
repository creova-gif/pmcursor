# PMCursor

PMCursor checks product requirements documents against repositories. It indexes Pydantic models, Zod schemas, FastAPI routes, Next.js App Router routes, OpenAPI specs, SQL DDL tables, and architecture decision records. It also indexes telemetry events for PostHog, Vercel Analytics, Langfuse, and BigQuery, then flags contract drift and fabricated `file:line` citations.

## Architecture and adapted patterns

PMCursor adapts plugin packaging and CLI conventions from [`cursor/plugins`](https://github.com/cursor/plugins) and workflow gates from [`garrytan/gstack`](https://github.com/garrytan/gstack).

| Source | Upstream file | PMCursor file |
|:---|:---|:---|
| `cursor/plugins` | `schemas/plugin.schema.json` and `scripts/validate-plugins.mjs` | [.cursor-plugin/plugin.json](.cursor-plugin/plugin.json), [.claude-plugin/plugin.json](.claude-plugin/plugin.json), and [src/pmcursor/plugin_validator.py](src/pmcursor/plugin_validator.py) |
| `cursor/plugins` | `cli-for-agent/skills/cli-for-agents/SKILL.md` | [src/pmcursor/cli.py](src/pmcursor/cli.py) |
| `cursor/plugins` | `agent-compatibility/README.md` | `SpecAlignmentScore` in [src/pmcursor/drift.py](src/pmcursor/drift.py) |
| `garrytan/gstack` | `office-hours/SKILL.md` | [skills/pm-office-hours/SKILL.md](skills/pm-office-hours/SKILL.md) |
| `garrytan/gstack` | `spec/SKILL.md` | [skills/pm-spec/SKILL.md](skills/pm-spec/SKILL.md) |
| `garrytan/gstack` | `review/SKILL.md` and `ship/SKILL.md` | [skills/pm-drift/SKILL.md](skills/pm-drift/SKILL.md) and [skills/pm-ship-readiness/SKILL.md](skills/pm-ship-readiness/SKILL.md) |

## Run the CLI

1. Index repository contracts into JSON.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli index --repo . --json
	```
2. Audit a PRD for schema, route, and telemetry drift plus fabricated `file:line` citations.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli drift --prd PROJECT_SPEC.md --repo . --md
	```
3. Repair shifted `file:line` citations and mismatched field types in a PRD. Pass `--write` to apply changes.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli fix-prd --prd PROJECT_SPEC.md --repo . --dry-run
	```
4. Map a git diff to impacted contracts and PRD references.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli pr-impact --prd PROJECT_SPEC.md --repo . --base main
	```
5. Generate an interactive split-pane HTML spec canvas.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli canvas --prd PROJECT_SPEC.md --repo . --output canvas.html
	```
6. Validate the Cursor and Claude plugin manifests.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli validate-plugin --repo .
	```
7. Run the evaluation benchmark.
	```bash
	PYTHONPATH=src python3 -m pmcursor.cli eval --json
	```

## Evaluation results

Run `PYTHONPATH=src python3 -m pmcursor.cli eval --json` to execute [src/pmcursor/eval_runner.py](src/pmcursor/eval_runner.py) against the seeded FastAPI and Pydantic fixture. The fixture contains 5 contract mismatches and 2 fabricated citations.

| Metric | Target | Result |
|:---|:---|:---|
| Schema and route mismatch recall | `>= 85.0%` | `100.0%` (`5/5`) |
| Unflagged fabricated file citations | `0` | `0` (`2/2` caught) |
| Plugin manifest and component check | `VALID` | `VALID` (`6/6` files) |

## Install the plugin in Cursor

Link this repository into your local Cursor plugins folder:

```bash
mkdir -p ~/.cursor/plugins/local
ln -sfn "$(pwd)" ~/.cursor/plugins/local/pmcursor
```

## References

- [Product specification and GTM doc](https://docs.google.com/document/d/1yNfo6zNq6T2POAKWvcUkmFM7yxDONYvYq8_wYpoJuT0/edit?usp=drivesdk&ouid=110227624285917376281)
- [Portfolio strategy](https://docs.google.com/document/d/12Wpg5mMGnjnl2uhMBTOR0QqRzQj8kwfzTLpvLoRuB5Q/edit?usp=drivesdk&ouid=110227624285917376281)
- [ADR-001 on AST contract indexing](docs/adr/001-contract-first-repo-indexing.md)
- [ADR-002 on plugin and skill architecture](docs/adr/002-cursor-plugin-and-gstack-skill-architecture.md)
- [Engineering standards](AGENTS.md) and [threat model](docs/THREAT_MODEL.md)
