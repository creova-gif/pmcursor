# Telemetry verification (`pmcursor telemetry-verify`)

## Sub-features

- Verify observed runtime telemetry events against indexed
  `TelemetryContract` definitions — catches events emitted but not specced
  and properties added/dropped.
- Event source: `--events-file <json|ndjson>` OR `--source langfuse|bigquery`
  (live fetch, `--limit`, default 500).
- `--json` emits `TelemetryVerificationReport`.

## How to get to it (user POV)

A PM exports recent telemetry events and runs
`pmcursor telemetry-verify --repo . --events-file events.json` to check the
live stream still matches the `telemetry:` contracts in the spec. The
`--source` form pulls straight from Langfuse or BigQuery instead of a file.
`POST /v1/telemetry/verify` is the API twin.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor telemetry-verify --repo . \
  --events-file <events.ndjson> --json > telem.json
echo $?   # expect 0
```

Proof of working: `TelemetryVerificationReport` has `total_code_events`,
`total_observed_events`, `matched_events`, and `items` — each item an
`event_name`, `citation`, `status` (`unindexed_event`, `missing_properties`,
`extra_properties`). Verified: one observed `spec_viewed` event produced an
`unindexed_event` item with `extra_properties: ["user_id"]` — this repo has
no indexed telemetry contracts so every observed event is unindexed.

## Gotchas

- `ObservedTelemetryEvent` uses `event_name` (not `name`) — a `name` field is
  silently dropped and the event is unnamed.
- This repo indexes `telemetry: 0` contracts, so `matched_events` is always
  0 here — correct for this repo, not a broken matcher.
- `--events-file` accepts a JSON array or NDJSON (one event per line).
- `--source` needs env credentials for the connector (e.g. Langfuse
  basic-auth or BigQuery service account) — without them it errors, which is
  the correct failure to capture.
