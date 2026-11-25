from __future__ import annotations

import tempfile
from pathlib import Path

from pmcursor.drift import check_spec_drift
from pmcursor.indexer import index_repository
from pmcursor.models import EvalBenchmarkResult

SAMPLE_MODELS_PY = '''from pydantic import BaseModel, Field


class SubscriptionPlan(BaseModel):
    plan_id: str
    org_id: str
    monthly_price_cents: int
    seat_limit: int = Field(default=10)
    is_active: bool = True


class DriftWebhookPayload(BaseModel):
    repo_full_name: str
    pr_number: int
    commit_sha: str
'''

SAMPLE_ROUTES_PY = '''from fastapi import APIRouter
from app.models import DriftWebhookPayload, SubscriptionPlan

router = APIRouter(prefix="/api/v1")


@router.get("/plans/{plan_id}", response_model=SubscriptionPlan)
async def get_plan(plan_id: str) -> SubscriptionPlan:
    return SubscriptionPlan(
        plan_id=plan_id,
        org_id="org_1",
        monthly_price_cents=2900,
    )


@router.post("/webhooks/github")
async def handle_github_webhook(payload: DriftWebhookPayload) -> dict[str, str]:
    return {"status": "queued"}
'''

SAMPLE_ADR_MD = '''# ADR-001: Contract-first indexing
- **Status:** Accepted
- **Owner:** Justin Mafie

## Context
Index Pydantic and FastAPI contracts deterministically.
'''

SEEDED_PRD_MD = '''# PRD: Billing and GitHub drift webhook

References `ADR-001` (`docs/adr/001-contract-first.md:1`).

## Current State
- Models defined in `app/models.py:4` and `app/models.py:12`.
- Routes implemented in `app/routes.py:8` and `app/routes.py:18`.
- Legacy billing helper in `app/nonexistent_service.py:44` and `app/models.py:999`.

## Contract Specifications
- `SubscriptionPlan.plan_id: str`
- `SubscriptionPlan.org_id: str`
- `SubscriptionPlan.monthly_price_cents: float`
- `SubscriptionPlan.billing_cycle: str`
- `AuditLogEntry.event_id: str`
- `GET /api/v1/plans/{plan_id}`
- `PUT /api/v1/webhooks/github`
- `DELETE /api/v1/plans/{plan_id}`

## Acceptance Criteria
1. Card: `protects=plan lookup and webhook ingestion; fails_when=schema drift or 422 payload error; no_claim=live Stripe webhook signature verification`

## Out of Scope
- Multi-currency tax calculation.

## Rollback Plan
- Revert webhook router registration and fall back to CLI drift check.
'''


def run_eval_benchmark() -> EvalBenchmarkResult:
    """Run deterministic spec-vs-code drift benchmark verifying >=85% recall and 0 unflagged fabricated citations."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        root = Path(tmp_dir)
        app_dir = root / "app"
        adr_dir = root / "docs" / "adr"
        app_dir.mkdir(parents=True)
        adr_dir.mkdir(parents=True)

        (app_dir / "models.py").write_text(SAMPLE_MODELS_PY, encoding="utf-8")
        (app_dir / "routes.py").write_text(SAMPLE_ROUTES_PY, encoding="utf-8")
        (adr_dir / "001-contract-first.md").write_text(SAMPLE_ADR_MD, encoding="utf-8")

        repo_map = index_repository(root)
        report = check_spec_drift(
            SEEDED_PRD_MD,
            repo_map,
            prd_path="eval_seeded_prd.md",
            repo_root=root,
        )

    seeded_mismatches = 5
    mismatch_categories = {
        "type_mismatch",
        "missing_field",
        "missing_model",
        "method_mismatch",
        "missing_route",
    }
    detected_mismatches = sum(
        1 for f in report.findings if f.category in mismatch_categories
    )
    recall = min(1.0, detected_mismatches / seeded_mismatches)

    seeded_fabricated = 2
    detected_fabricated = report.fabricated_citations_count
    unflagged_fabricated = max(0, seeded_fabricated - detected_fabricated)

    passed = recall >= 0.85 and unflagged_fabricated == 0

    return EvalBenchmarkResult(
        passed=passed,
        seeded_mismatches=seeded_mismatches,
        detected_mismatches=detected_mismatches,
        recall=recall,
        seeded_fabricated_citations=seeded_fabricated,
        detected_fabricated_citations=detected_fabricated,
        unflagged_fabricated_citations=unflagged_fabricated,
        alignment_score=report.alignment_score.overall_score,
    )
