from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from api import compute_pr_impact, handle_github_webhook, verify_github_signature
from pmcursor import (
    check_spec_drift,
    fix_prd_markdown,
    format_drift_report_markdown,
    healthcheck,
    index_repository,
    run_eval_benchmark,
    validate_plugin_manifests,
)
from pmcursor.cli import main
from web.canvas import render_split_pane_canvas

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_healthcheck() -> None:
    assert healthcheck() == "ok"


def test_plugin_manifests_are_valid() -> None:
    result = validate_plugin_manifests(REPO_ROOT)
    assert result.valid is True, f"Plugin validation errors: {result.errors}"
    assert result.plugin_name == "pmcursor"
    assert result.version == "0.3.0"
    assert "skills/pm-office-hours/SKILL.md" in result.checked_components
    assert "skills/pm-spec/SKILL.md" in result.checked_components
    assert "skills/pm-drift/SKILL.md" in result.checked_components
    assert "skills/pm-ship-readiness/SKILL.md" in result.checked_components
    assert "agents/spec-drift-auditor.md" in result.checked_components
    assert "rules/pmcursor-citations.mdc" in result.checked_components


def test_eval_benchmark_exceeds_acceptance_thresholds() -> None:
    bench = run_eval_benchmark()
    assert bench.passed is True
    assert bench.recall >= 0.85
    assert bench.recall == 1.0
    assert bench.unflagged_fabricated_citations == 0
    assert bench.detected_fabricated_citations == 2


def test_indexer_and_clean_spec_drift_done(tmp_path: Path) -> None:
    app_dir = tmp_path / "src"
    adr_dir = tmp_path / "docs" / "adr"
    app_dir.mkdir(parents=True)
    adr_dir.mkdir(parents=True)

    (app_dir / "schemas.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class FeatureSpec(BaseModel):\n"
        "    spec_id: str\n"
        "    owner_email: str\n"
        "    priority: int = 1\n",
        encoding="utf-8",
    )
    (app_dir / "api.py").write_text(
        "from fastapi import FastAPI\n"
        "from src.schemas import FeatureSpec\n\n"
        "app = FastAPI()\n\n"
        "@app.get('/specs/{spec_id}', response_model=FeatureSpec)\n"
        "def read_spec(spec_id: str) -> FeatureSpec:\n"
        "    return FeatureSpec(spec_id=spec_id, owner_email='pm@example.com')\n",
        encoding="utf-8",
    )
    (adr_dir / "001-architecture.md").write_text(
        "# ADR-001: Contract Architecture\n- **Status:** Accepted\n",
        encoding="utf-8",
    )

    repo_map = index_repository(tmp_path)
    assert len(repo_map.models) == 1
    assert repo_map.models[0].name == "FeatureSpec"
    assert repo_map.models[0].citation == "src/schemas.py:3"
    assert len(repo_map.routes) == 1
    assert repo_map.routes[0].method == "GET"
    assert repo_map.routes[0].path == "/specs/{spec_id}"
    assert len(repo_map.adrs) == 1
    assert repo_map.adrs[0].adr_id == "ADR-001"

    clean_prd = (
        "# Feature Spec PRD\n\n"
        "Implements `ADR-001` (`docs/adr/001-architecture.md:1`).\n"
        "Backed by `src/schemas.py:3` and `src/api.py:6`.\n\n"
        "## Contracts\n"
        "- `FeatureSpec.spec_id: str`\n"
        "- `FeatureSpec.owner_email: str`\n"
        "- `FeatureSpec.priority: int`\n"
        "- `GET /specs/{spec_id}`\n\n"
        "## Acceptance Criteria\n"
        "1. `protects=spec retrieval; fails_when=missing field; no_claim=auth middleware`\n\n"
        "## Out of Scope\n"
        "- Batch export.\n\n"
        "## Rollback Plan\n"
        "- Revert route deployment.\n"
    )
    report = check_spec_drift(clean_prd, repo_map, repo_root=tmp_path)
    assert report.status == "DONE"
    assert report.fabricated_citations_count == 0
    assert report.findings == []
    assert report.alignment_score.overall_score == 100

    md_output = format_drift_report_markdown(report)
    assert "100/100" in md_output
    assert "No spec-vs-code drift or fabricated citations detected." in md_output


def test_multistack_zod_sql_openapi_and_telemetry(tmp_path: Path) -> None:
    web_dir = tmp_path / "web"
    route_dir = tmp_path / "app" / "api" / "plans" / "[id]"
    db_dir = tmp_path / "db"
    web_dir.mkdir(parents=True)
    route_dir.mkdir(parents=True)
    db_dir.mkdir(parents=True)

    (web_dir / "plan.ts").write_text(
        "import { z } from 'zod';\n"
        "import posthog from 'posthog-js';\n\n"
        "export interface BillingSummary {\n"
        "  plan_id: string;\n"
        "  seats: number;\n"
        "}\n\n"
        "export const PlanCard = z.object({\n"
        "  plan_id: z.string(),\n"
        "  seat_count: z.number(),\n"
        "  trial: z.boolean().optional(),\n"
        "});\n\n"
        "export function logPlanView(orgId: string) {\n"
        "  posthog.capture('plan_viewed', { org_id: orgId, source: 'canvas' });\n"
        "}\n",
        encoding="utf-8",
    )
    (route_dir / "route.ts").write_text(
        "export async function GET() {\n"
        "  return Response.json({ ok: true });\n"
        "}\n",
        encoding="utf-8",
    )
    (db_dir / "schema.sql").write_text(
        "CREATE TABLE IF NOT EXISTS workspace_billing (\n"
        "  org_id TEXT NOT NULL,\n"
        "  seats INTEGER NOT NULL,\n"
        "  active BOOLEAN\n"
        ");\n\n"
        "CREATE TABLE telemetry_invoice_paid (\n"
        "  org_id TEXT NOT NULL,\n"
        "  amount_cents INTEGER NOT NULL\n"
        ");\n",
        encoding="utf-8",
    )
    (tmp_path / "openapi.json").write_text(
        json.dumps(
            {
                "openapi": "3.1.0",
                "paths": {"/v1/health": {"get": {"operationId": "getHealth"}}},
                "components": {
                    "schemas": {
                        "HealthStatus": {
                            "type": "object",
                            "required": ["ok"],
                            "properties": {"ok": {"type": "boolean"}},
                        }
                    }
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    (tmp_path / "openapi.yaml").write_text(
        "openapi: 3.1.0\n"
        "paths:\n"
        "  /v1/billing:\n"
        "    post:\n"
        "      operationId: createBilling\n"
        "components:\n"
        "  schemas:\n"
        "    BillingRecord:\n"
        "      type: object\n"
        "      properties:\n"
        "        record_id:\n"
        "          type: string\n",
        encoding="utf-8",
    )

    repo_map = index_repository(tmp_path)
    model_names = {m.name for m in repo_map.models}
    assert {
        "PlanCard",
        "BillingSummary",
        "workspace_billing",
        "HealthStatus",
        "BillingRecord",
    }.issubset(model_names)
    route_sigs = {(r.method, r.path) for r in repo_map.routes}
    assert ("GET", "/api/plans/{id}") in route_sigs
    assert ("GET", "/v1/health") in route_sigs
    assert ("POST", "/v1/billing") in route_sigs
    telemetry_names = {t.event_name for t in repo_map.telemetry}
    assert {"plan_viewed", "invoice_paid"}.issubset(telemetry_names)

    prd = (
        "# Multi-Stack PRD\n\n"
        "- `PlanCard.plan_id: str`\n"
        "- `BillingSummary.plan_id: str`\n"
        "- `workspace_billing.seats: int`\n"
        "- `HealthStatus.ok: bool`\n"
        "- `BillingRecord.record_id: str`\n"
        "- `GET /api/plans/{id}`\n"
        "- `GET /v1/health`\n"
        "- `POST /v1/billing`\n"
        "- `telemetry: plan_viewed(org_id)`\n"
        "- `telemetry: missing_event(org_id)`\n"
    )
    report = check_spec_drift(prd, repo_map, repo_root=tmp_path)
    assert report.status == "DONE_WITH_CONCERNS"
    categories = [f.category for f in report.findings]
    assert categories == ["missing_telemetry"]


def test_fix_prd_self_healing_and_idempotency(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Plan(BaseModel):\n"
        "    price_cents: int\n",
        encoding="utf-8",
    )
    prd_file = tmp_path / "PRD.md"
    original_prd = (
        "# Plan PRD\n"
        "Model at `app/models.py:99`.\n"
        "- `Plan.price_cents: float`\n"
    )
    prd_file.write_text(original_prd, encoding="utf-8")

    rc_dry = main(["fix-prd", "--prd", str(prd_file), "--repo", str(tmp_path), "--dry-run"])
    assert rc_dry == 0
    assert prd_file.read_text(encoding="utf-8") == original_prd

    repo_map = index_repository(tmp_path)
    res1 = fix_prd_markdown(original_prd, repo_map, prd_path="PRD.md", repo_root=tmp_path)
    assert res1.fixed_citations_count == 1
    assert res1.fixed_types_count == 1
    assert "`app/models.py:3`" in res1.updated_markdown
    assert "`Plan.price_cents: int`" in res1.updated_markdown

    rc_write = main(["fix-prd", "--prd", str(prd_file), "--repo", str(tmp_path), "--write"])
    assert rc_write == 0
    healed = prd_file.read_text(encoding="utf-8")
    res2 = fix_prd_markdown(healed, repo_map, prd_path="PRD.md", repo_root=tmp_path)
    assert res2.fixed_citations_count == 0
    assert res2.fixed_types_count == 0


def test_pr_impact_and_webhook_signature(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class Order(BaseModel):\n"
        "    order_id: str\n"
        "    total_cents: int\n",
        encoding="utf-8",
    )
    prd_md = "# Order PRD\n- `Order.order_id: str`\n"
    diff_text = (
        "diff --git a/app/models.py b/app/models.py\n"
        "--- a/app/models.py\n"
        "+++ b/app/models.py\n"
        "@@ -4,2 +4,2 @@ class Order(BaseModel):\n"
        "-    total_cents: float\n"
        "+    total_cents: int\n"
    )
    repo_map = index_repository(tmp_path)
    impact = compute_pr_impact(prd_md, diff_text, repo_map, org_id="acme")
    assert len(impact.touched_contracts) == 1
    assert impact.touched_contracts[0].name == "Order"
    assert impact.touched_contracts[0].referenced_in_prd is True
    assert "acme" in impact.markdown_comment

    secret = "whsec_test_secret"
    body = json.dumps(
        {
            "org_id": "acme",
            "prd_markdown": prd_md,
            "diff_text": diff_text,
            "prd_path": "PRD.md",
            "repo_root": str(tmp_path),
        }
    ).encode("utf-8")
    good_sig = "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    assert verify_github_signature(body, good_sig, secret) is True
    assert verify_github_signature(body, "sha256=deadbeef", secret) is False
    webhook_report = handle_github_webhook(
        body,
        good_sig,
        secret,
        allowed_workspace_root=tmp_path,
    )
    assert webhook_report.org_id == "acme"

    with pytest.raises(PermissionError):
        handle_github_webhook(body, "sha256=deadbeef", secret)

    allowed_root = tmp_path / "allowed_only"
    allowed_root.mkdir()
    with pytest.raises(PermissionError):
        handle_github_webhook(
            body,
            good_sig,
            secret,
            allowed_workspace_root=allowed_root,
        )


def test_split_pane_canvas_and_xss_safety(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass User(BaseModel):\n    user_id: str\n",
        encoding="utf-8",
    )
    prd_md = "# PRD <script>alert(1)</script>\n- `User.user_id: str`\n"
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text(prd_md, encoding="utf-8")
    out_html = tmp_path / "canvas.html"

    repo_map = index_repository(tmp_path)
    report = check_spec_drift(prd_md, repo_map, repo_root=tmp_path)
    html_doc = render_split_pane_canvas(prd_md, repo_map, report)
    assert "<script>alert(1)</script>" not in html_doc
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html_doc
    assert 'aria-label="Living PRD"' in html_doc
    assert 'aria-label="Codebase Contracts"' in html_doc

    rc = main(
        ["canvas", "--prd", str(prd_file), "--repo", str(tmp_path), "--output", str(out_html)]
    )
    assert rc == 0
    assert out_html.is_file()


def test_security_path_containment_and_binary_resilience(tmp_path: Path) -> None:
    app_dir = tmp_path / "app"
    app_dir.mkdir(parents=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Item(BaseModel):\n    item_id: str\n",
        encoding="utf-8",
    )
    (app_dir / "binary.py").write_bytes(b"\xff\xfe\x00\x80invalid_utf8")
    (app_dir / "huge.ts").write_bytes(b"x" * 2_200_000)

    repo_map = index_repository(tmp_path)
    assert "app/huge.ts" not in repo_map.indexed_files
    assert len(repo_map.models) == 1

    traversal_prd = "# Traversal\nBad link: `../../outside/secret.py:1`\n"
    report = check_spec_drift(traversal_prd, repo_map, repo_root=tmp_path)
    assert report.status == "BLOCKED"
    assert report.fabricated_citations_count == 1
    assert any(
        f.category == "fabricated_citation" and "escapes repository root" in f.message
        for f in report.findings
    )


def test_cli_commands(tmp_path: Path) -> None:
    rc_eval = main(["eval", "--json"])
    assert rc_eval == 0

    rc_plugin = main(["validate-plugin", "--repo", str(REPO_ROOT), "--json"])
    assert rc_plugin == 0

    out_file = tmp_path / "repo_map.json"
    rc_index = main(
        ["index", "--repo", str(REPO_ROOT), "--output", str(out_file), "--json"]
    )
    assert rc_index == 0
    loaded = json.loads(out_file.read_text(encoding="utf-8"))
    assert len(loaded["models"]) >= 8
    assert len(loaded["adrs"]) >= 2

    rc_drift = main(
        ["drift", "--prd", str(REPO_ROOT / "PROJECT_SPEC.md"), "--repo", str(REPO_ROOT), "--md"]
    )
    assert rc_drift == 0
