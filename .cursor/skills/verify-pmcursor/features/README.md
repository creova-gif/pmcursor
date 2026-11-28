# PMCursor feature map

The maintained list of user-facing features, each with the drive recipe and the
observable end state that proves it works. When a proof touches a feature, use
its file here; when a feature changes, update its file. A proof that only
drives one convenient entry point is incomplete — the map lists them all.

| Feature | File | Primary surface |
|---|---|---|
| Repository indexing (`pmcursor index`) | [index.md](index.md) | CLI |
| Spec drift audit (`pmcursor drift`) | [drift.md](drift.md) | CLI + API `/v1/drift/audit` |
| PRD repair (`pmcursor fix-prd`) | [fix-prd.md](fix-prd.md) | CLI |
| PR impact analysis (`pmcursor pr-impact`) | [pr-impact.md](pr-impact.md) | CLI |
| Edge-case checklist (`pmcursor checklist`) | [checklist.md](checklist.md) | CLI + API `/v1/checklist` |
| Split-pane spec canvas (`pmcursor canvas`) | [canvas.md](canvas.md) | CLI + API `/v1/canvas` |
| Plugin manifest validation (`pmcursor validate-plugin`) | [validate-plugin.md](validate-plugin.md) | CLI |
| Evaluation benchmark (`pmcursor eval`) | [eval.md](eval.md) | CLI |
| Ticket auditing (`pmcursor ticket-sync`) | [ticket-sync.md](ticket-sync.md) | CLI + API webhooks |
| Release notes (`pmcursor release-notes`) | [release-notes.md](release-notes.md) | CLI |
| Feature-flag audit (`pmcursor flags`) | [flags.md](flags.md) | CLI + API `/v1/flags/audit` |
| Multi-repo federation (`pmcursor federate`) | [federate.md](federate.md) | CLI |
| Telemetry verification (`pmcursor telemetry-verify`) | [telemetry-verify.md](telemetry-verify.md) | CLI + API `/v1/telemetry/verify` |
| Org dashboard (`pmcursor dashboard`) | [dashboard.md](dashboard.md) | CLI + API `/v1/dashboard` |
| Diagnostics (`pmcursor doctor`) | [doctor.md](doctor.md) | CLI |
| Comment publishing (`pmcursor publish`) | [publish.md](publish.md) | CLI |
| Drift summarizer (`pmcursor summarize`) | [summarize.md](summarize.md) | CLI + API `/v1/summarize` |
| GitHub App management (`pmcursor github-app`) | [github-app.md](github-app.md) | CLI + API `/v1/github-app/*` |
| MCP server (`pmcursor mcp`) | [mcp.md](mcp.md) | MCP stdio |
| HTTP API service (`pmcursor serve`) | [api-server.md](api-server.md) | HTTP |

All 19 subcommands mapped. Last full proof: 2026-11-28 — every command driven
live, outputs captured under `.pmcursor-verify/evidence/feature-map-2026-11-28/`.
