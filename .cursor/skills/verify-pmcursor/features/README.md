# PMCursor feature map

The maintained list of user-facing features, each with the drive recipe and the
observable end state that proves it works. When a proof touches a feature, use
its file here; when a feature changes, update its file. A proof that only
drives one convenient entry point is incomplete — the map lists them all.

| Feature | File | Primary surface |
|---|---|---|
| Repository indexing (`pmcursor index`) | [index.md](index.md) | CLI |
| Spec drift audit (`pmcursor drift`) | [drift.md](drift.md) | CLI + API `/v1/drift/audit` |
| Edge-case checklist (`pmcursor checklist`) | [checklist.md](checklist.md) | CLI + API `/v1/checklist` |
| Split-pane spec canvas (`pmcursor canvas`) | [canvas.md](canvas.md) | CLI + API `/v1/canvas` |
| HTTP API service (`pmcursor serve`) | [api-server.md](api-server.md) | HTTP |

## Not yet mapped

These subcommands exist and follow the same CLI pattern — add a feature file
when a task first needs to verify them: `fix-prd`, `pr-impact`,
`release-notes`, `flags`, `federate`, `telemetry-verify`, `dashboard`,
`ticket-sync`, `publish`, `validate-plugin`, `eval`, `mcp`, `doctor` (already
the Doctor step in `../SKILL.md`).
