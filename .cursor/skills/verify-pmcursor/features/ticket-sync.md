# Ticket auditing (`pmcursor ticket-sync`)

## Sub-features

- Audit a Linear or Jira ticket's body against `RepoMap` contracts — same
  drift engine as `drift`, but the "spec" is the ticket body.
- `--provider linear|jira` (default `linear`), `--fail-on-drift` exits 1 on
  findings.
- `--md` (default) emits a ticket comment body; `--json` emits
  `TicketSyncReport`.

## How to get to it (user POV)

A PM pastes a Linear ticket body into `body.md` and runs
`pmcursor ticket-sync --id ENG-42 --title "..." --body-file body.md --repo .`
to check the ticket's contract claims against the code before picking it up.
The `POST /v1/webhooks/linear` and `POST /v1/webhooks/jira` endpoints automate
the same audit on webhook events.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor ticket-sync --id ENG-42 --title "Add UserProfile" \
  --body-file <ticket.md> --repo . --json
echo $?   # expect 0
```

Proof of working: `TicketSyncReport` has `ticket_id`, `provider`, `title`,
and a nested `drift_report` (same `DriftReport` shape as `drift.md`) with
`status`, `alignment_score`, and `findings`. Verified: a ticket citing a
nonexistent model produced a DONE report with findings and a scored
`alignment_score` object.

## Gotchas

- No network is touched — this audits a local body file only. Fetching the
  ticket from Linear/Jira is the webhook endpoints' job, not this command's.
- `prd_path` inside the nested report is `linear:ENG-42` / `jira:ENG-42`,
  not a filesystem path — expected.
