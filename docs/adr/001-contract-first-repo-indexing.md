# ADR-001: Contract-first repository indexing

- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
Product managers who write or review PRDs need exact `file:line` citations. Passing an entire repository into a language model prompt wastes context tokens and produces fabricated file paths.

## Decision
Extract explicit code contracts into a JSON `RepoMap` with Python's `ast` module in `src/pmcursor/indexer.py`:
1. Pydantic `BaseModel` subclasses, dataclasses, and typed schemas with field names, type annotations, and `file:line` numbers.
2. FastAPI and `APIRouter` route decorators with HTTP methods, paths, request models, response models, and `file:line` numbers.
3. Architecture decision records in `docs/adr/*.md` with ID, title, status, and line numbers.

`check_spec_drift` in `src/pmcursor/drift.py` compares PRDs against `RepoMap` and checks every cited file path and line number on disk.

## Alternatives considered
1. Full repository prompting increases cost and misses multi-file field mismatches.
2. Embedding search splits class definitions across chunks and cannot verify every field on a model.
3. Runtime OpenAPI export requires starting the server and misses unmounted routers and internal models.

## Consequences and failure modes
- Static AST parsing finishes in under 50 ms on local repositories and needs no network access.
- Dynamic routes created at runtime do not appear in the static AST walk. Specs must record unverified runtime behavior in the `no_claim` field of their acceptance cards.
