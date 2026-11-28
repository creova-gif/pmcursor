# ADR-005: PR automation — merge queue, check-run reruns, and failure comments

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
ADR-004 shipped the pull_request automation loop, but three gaps remained: merge-queue repos never got audits (`merge_group` events were unhandled and fell through to payload validation), clicking "Re-run" on a failed pmcursor check did nothing (the app wasn't subscribed to `check_run`), and a failing check run carried diagnostics only inside the Checks tab — contributors scanning the PR conversation saw a red X with no explanation.

## Decision
Extend `src/pmcursor/github_pr_automation.py` into a shared `_run_pipeline` keyed on an explicit change context (repo, base/head sha, PR number, installation) with three event adapters:

1. `process_pull_request_event` — unchanged behavior; parses the pull_request payload.
2. `process_merge_group_event` — handles `merge_group` `checks_requested`; the queue's `head_ref` (`refs/heads/gh-readonly-queue/<base>/pr-N-<sha>`) is parsed for the PR number so failure comments still land on the right PR.
3. `process_check_run_rerequest` — handles `check_run` `rerequested`, filtered by check-run name; `check_run.pull_requests[]` supplies the base sha and PR number. Returns `None` for foreign check runs.

`run_pull_request_automation` dispatches on the payload's event key. The webhook handler treats any payload carrying `pull_request`/`merge_group`/`check_run` as an automation event, queues it only for eligible actions (`PR_AUTOMATION_ACTIONS`, `checks_requested`, `rerequested` with name match), and acks the rest.

On `failure` conclusions with a resolved PR number, the pipeline upserts a `<!-- pmcursor-drift -->` marker comment (`issues` API: list → PATCH existing or POST new) containing the impact markdown and rendered findings — subsequent pushes update the same comment instead of spamming. `create_app(pr_failure_comments=...)` / `PMCURSOR_GITHUB_APP_PR_COMMENTS=0` disables it.

`build_app_manifest` gained `merge_queues: read` and the `check_run`/`merge_group` events (`issues: write` was already present for comments).

## Alternatives considered
1. A check-run-only UX with no PR comments — rejected: Checks-tab output is hidden behind a click and disappears on re-run; a marker comment keeps the current verdict in the conversation.
2. Creating a fresh comment per run — rejected: repeated pushes on a failing PR would flood the thread; upserting a marker comment is the standard bot pattern.
3. Rerunning on any `check_run` event — rejected: GitHub delivers `rerequested` for every subscribed app when any check is re-run; filtering on our check-run name avoids wasted pipeline executions.
4. Skipping merge-queue support — rejected: merge-queue repos are exactly where drift gates matter most; the tarball+compare pipeline transfers wholesale once keyed on explicit shas.

## Consequences and failure modes
- Comment upsert lists up to 100 comments per run; on threads with more, a second marker comment may be created — acceptable drift, self-heals as the newer comment is found first on later runs.
- `gh-readonly-queue` ref parsing is a GitHub-internal format; if it changes, failure comments for merge-queue runs degrade to check-run-only output (PR number resolves to 0, comment skipped).
- Merge-queue check runs post to the merge-group head sha (the ephemeral merge commit), which is correct — that commit is what the queue evaluates.
