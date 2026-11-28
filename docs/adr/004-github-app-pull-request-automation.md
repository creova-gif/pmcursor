# ADR-004: GitHub App pull-request automation pipeline

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
M19 made PMCursor installable as a GitHub App (manifest flow, installation tokens, lifecycle webhooks), but `pull_request` events were only acknowledged. The product promise is a drift audit posted back to the PR automatically. Doing that needs repo content the webhook payload does not carry: the PR head tree (to index), the PRD markdown (the spec), and the PR diff (for PR-impact analysis).

## Decision
Add `src/pmcursor/github_pr_automation.py` and run it as a FastAPI `BackgroundTask` on `pull_request` webhook events when a `GitHubAppAuth` is configured:

1. `GitHubRepoClient` wraps installation-token-authenticated GitHub REST calls: tarball download, file content (`contents` API, base64), a `compare/{base}...{head}` diff (`Accept: application/vnd.github.diff`), and check-run creation.
2. `process_pull_request_event` orchestrates: mint an installation token → stream the head-SHA tarball into a temp dir (50MB compressed cap; `tarfile filter="data"` plus cumulative uncompressed-size and member-count caps to bound decompression) → `index_repository` → fetch the PRD from a candidate path list → fetch the `base.sha...head.sha` compare diff (pinned to the event's immutable commits so a racing push cannot substitute a newer diff against the older indexed tree; 1MB cap) → `compute_pr_impact` → post a check run whose conclusion derives from the deterministic `DriftReport` status (`success`/`failure`/`neutral`) and whose output carries the finding list.
3. The webhook handler queues the task only for actions `opened`, `synchronize`, `reopened`, `ready_for_review` and only when `create_app(github_app=...)` resolved an auth (env `PMCURSOR_GITHUB_APP_ID` + `PMCURSOR_GITHUB_APP_PRIVATE_KEY`/`_PATH`); `PMCURSOR_GITHUB_APP_AUTO_RUN=0` disables it. Responses stay fast (`202`-style "accepted"/"queued") since GitHub times out deliveries at ~10s.
4. Pipeline failures inside the background task attempt a `neutral` check run so a broken pipeline never fails silently on the PR.
5. If no PRD file exists at any candidate path (`PMCURSOR_PRD_PATH`, `PROJECT_SPEC.md`, `PRD.md`, `docs/PRD.md`, `.pmcursor/prd.md`) — including a candidate that exists but is empty — the check run posts `neutral` listing the paths tried; the app skips judgement rather than fabricating a spec.

## Alternatives considered
1. Cloning via `git clone` with the installation token — rejected: adds a git subprocess + credential-in-argv handling when the tarball endpoint gives the same tree over HTTPS.
2. Blocking the webhook response on the pipeline — rejected: GitHub redelivers on timeout, and indexing + two API calls can exceed the delivery deadline.
3. Commenting on the PR instead of a check run — rejected: check runs are the native verdict surface (they gate merges); the markdown impact comment remains available via `POST /v1/publish`.
4. Fetching the PRD from the merge base rather than head — rejected: drift should reflect what the PR *changes* the spec into; head is the reviewable state.

## Consequences and failure modes
- Background execution means webhook signature verification and dedup still gate entry, but pipeline errors surface only on the check run and server logs — an operator watching `pmcursor serve` logs is required for diagnosis.
- `tarfile filter="data"` requires Python ≥3.11.4; the project floor is 3.11 so this is safe within supported versions.
- Large repos (>50MB tarball) or oversized diffs (>1MB) are refused or truncated — the check run notes the truncation rather than guessing.
- The installation token is minted per event and cached with a refresh margin; it is never logged or included in check-run output.
