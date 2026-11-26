# Contributing to PMCursor

Thank you for contributing to PMCursor! Please follow the setup and quality guidelines below before opening a pull request.

## Prerequisites

- **Python:** 3.11+ (CI runs on Python 3.12)
- **Package manager:** [`uv`](https://docs.astral.sh/uv/) or `pip`

## Local Development Setup

Clone the repository and install PMCursor in editable mode with the optional server dependencies:

```bash
git clone https://github.com/creova-gif/pmcursor.git
cd pmcursor
pip install -e '.[server]'
```

If you use `uv`, you can create a virtual environment and install dependencies with:

```bash
uv venv
source .venv/bin/activate
uv pip install -e '.[server]'
```

## Quality Gates

Every pull request must pass all of the following checks locally before review:

1. **Linting (`ruff`):**
   ```bash
   uvx ruff check src indexer api web evals tests
   ```
2. **Strict type checking (`mypy`):**
   ```bash
   MYPYPATH=src mypy --strict src indexer api web evals tests
   ```
3. **Unit & integration tests (`pytest`):**
   ```bash
   pytest -v
   ```
4. **Plugin manifest & component validation:**
   ```bash
   PYTHONPATH=src python3 -m pmcursor.cli validate-plugin --repo .
   ```
5. **Evaluation benchmark:**
   ```bash
   PYTHONPATH=src python3 -m pmcursor.cli eval --json
   ```

## Architecture Decision Records (ADRs)

Record every non-trivial design choice in `docs/adr/` using [docs/adr/000-template.md](docs/adr/000-template.md) before or alongside your implementation. Number new ADRs sequentially (e.g., `004-short-title.md`).

## Pull Request Workflow

1. Create a focused branch from `main` (for example, `feat/my-change` or `fix/my-bug`).
2. Implement your changes following [AGENTS.md](AGENTS.md) standards (Python 3.12+ typing, Pydantic v2 models, no bare `except Exception: pass`, and no committed secrets or `.env` files).
3. Add or update deterministic unit tests covering your changes.
4. Run all quality gates listed above and verify they pass.
5. Update `CHANGELOG.md` under `## [Unreleased]` (and `docs/ROADMAP.md` if completing a milestone).
6. Open a pull request using `.github/PULL_REQUEST_TEMPLATE.md` with a clear summary and verification results.
