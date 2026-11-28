# Comment publishing (`pmcursor publish`)

## Sub-features

- Publish a comment to a GitHub PR, Linear issue, or Jira issue — the
  bi-directional half of the drift loop.
- `--provider github|linear|jira`, `--target owner/repo#N` (GitHub) or
  `ISSUE-ID` (Linear/Jira), `--jira-base-url` for self-hosted Jira.
- `--dry-run` builds the payload and prints it without any HTTP request —
  the no-credentials proof path.
- `--json` emits `PublishResult`.

## How to get to it (user POV)

After a drift or ticket audit a PM runs
`pmcursor publish --provider github --target owner/repo#42 --body-file
comment.md` to post the report back onto the PR — the same posting the
GitHub App does automatically in M21/M22.

## Driving it with the pmcursor CLI

```bash
cd /Users/justinmafie/Documents/antigravity/pmcursor
.venv/bin/pmcursor publish --provider github --target creova-gif/pmcursor#38 \
  --body-file <comment.md> --dry-run --json
echo $?   # expect 0
```

Proof of working: `PublishResult` has `provider`, `target_id`, `dry_run:
true`, `status_code: 0`, the resolved API `url`
(`.../issues/38/comments` — a PR is an issue for comments), and
`body_preview`. Verified against `creova-gif/pmcursor#38`.

## Gotchas

- `--dry-run` is the only credential-free path; without it the command reads
  a provider token from env and issues a real POST — always dry-run in
  verification.
- GitHub `--target` is `owner/repo#N` and resolves to the issue-comments URL,
  not a PR-reviews URL — expected, PRs are issues.
- `status_code: 0` on dry-run is "not sent", not an error.
