# PMCursor: Codebase-Aware AI IDE for Product Managers

- **Model:** Open-Source CLI/GitHub App + Team SaaS ($29-$49/PM/mo)
- **Thesis Alignment:** #01 Cursor for Product Managers, #62 Enterprise AI Automation
- **Full Google Doc Spec:** [PMCursor: Codebase-Aware AI IDE for Product Managers](https://docs.google.com/document/d/1yNfo6zNq6T2POAKWvcUkmFM7yxDONYvYq8_wYpoJuT0/edit?usp=drivesdk&ouid=110227624285917376281)
- **Portfolio Strategy:** [00 - Startup & Open-Source Cross-Project Strategy](https://docs.google.com/document/d/12Wpg5mMGnjnl2uhMBTOR0QqRzQj8kwfzTLpvLoRuB5Q/edit?usp=drivesdk&ouid=110227624285917376281)

## 1. Goal & Problem
Keep PRDs, edge-case checklists, and sprint tickets synced to live Git PRs, AST schemas, and BigQuery/Langfuse telemetry with 100% file-path citations.

## 2. Target Customer (ICP) & Monetization
Technical PMs, Heads of Product, and startup founders at 10-200 person software companies using GitHub + Linear/Jira.

## 3. Tech Stack
Python FastAPI + Tree-sitter AST indexer, Next.js split-pane UI, Anthropic Claude, GitHub Webhooks.

## 4. Evaluation & Acceptance Thresholds
0 fabricated file paths/symbols; >= 85% recall on intentional spec-vs-code schema mismatches.

## 5. Key Architectural Decision (ADR-001)
Index explicit code contracts (Pydantic/Zod/OpenAPI/SQL/ADRs) via Tree-sitter rather than stuffing raw repos into context.

## 6. Day 1–5 Quickstart
- [ ] Set up indexer/, api/, web/, and evals/ directories
- [ ] Build Tree-sitter/Pydantic extractor outputting a JSON map of models, routes, and ADRs
- [ ] Implement check_spec_drift(prd_md, repo_map) flagging mismatches with exact file:line citations
- [ ] Test on a public FastAPI repo and verify zero hallucinated file paths
