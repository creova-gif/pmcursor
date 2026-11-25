# ADR-002: Cursor plugin and GStack skill architecture

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
PMCursor runs inside coding agents such as Cursor, Claude Code, and Antigravity. We inspected `cursor/plugins` and `garrytan/gstack` to reuse their manifest schemas, CLI rules, and phase gates.

## Decision
Combine the plugin layout and CLI rules from `cursor/plugins` with the phase-gated skills from `garrytan/gstack`:
1. Ship `.cursor-plugin/plugin.json` and `.claude-plugin/plugin.json` at the repository root and validate both with `pmcursor validate-plugin`.
2. Build `src/pmcursor/cli.py` around the `cli-for-agent` rules. Every subcommand runs without interactive prompts, includes `Examples:` in `--help`, supports `--json` and `--md`, and prints a working command when arguments fail.
3. Score PRD alignment with the `agent-compatibility` 70/30 weighting formula: `round(deterministic_score * 0.7 + workflow_score * 0.3)`.
4. Provide four markdown skills under `skills/`: `pm-office-hours`, `pm-spec`, `pm-drift`, and `pm-ship-readiness`. Each skill runs `pmcursor index` or `pmcursor drift` and reports status with `DONE`, `DONE_WITH_CONCERNS`, `BLOCKED`, or `NEEDS_CONTEXT`.

## Alternatives considered
1. Building a standalone web app first adds deployment overhead before validating the core drift engine in local repositories.
2. Shipping markdown prompts without a Python CLI fails the zero-fabricated-path requirement because language models guess line numbers.

## Consequences and failure modes
- Developers and product managers can load the plugin locally in Cursor at `~/.cursor/plugins/local/pmcursor`.
- Version numbers across `.cursor-plugin/plugin.json`, `.claude-plugin/plugin.json`, and `pyproject.toml` must match. `test_plugin_manifests_are_valid` enforces this in CI.
