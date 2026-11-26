from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import pmcursor
from api import OrgDashboardSummary
from api.server import create_app
from pmcursor.cli import main
from pmcursor.telemetry_verify import TelemetryVerificationReport


def _create_sample_repo(base: Path) -> Path:
    app_dir = base / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class CheckoutOrder(BaseModel):\n"
        "    order_id: str\n"
        "    amount_cents: int\n",
        encoding="utf-8",
    )
    (app_dir / "routes.py").write_text(
        "from fastapi import APIRouter\n\n"
        "router = APIRouter()\n\n"
        "@router.post('/v1/orders')\n"
        "def create_order():\n"
        "    track_event('order_created', {'order_id': 'o1', 'amount_cents': 100})\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )
    (app_dir / "flags.py").write_text(
        "def is_new_checkout(ld_client, user) -> bool:\n"
        '    return ld_client.bool_variation("new-checkout", user, False)\n',
        encoding="utf-8",
    )
    (base / "PROJECT_SPEC.md").write_text(
        "# Checkout Spec\n\n"
        "Model `CheckoutOrder` has `order_id` (str) and `amount_cents` (int).\n"
        "Endpoint `POST /v1/orders` tracks `order_created`.\n",
        encoding="utf-8",
    )
    return base


def test_telemetry_verify_endpoint_auth_workspace_and_200(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_root = _create_sample_repo(workspace / "repo")
    outside = _create_sample_repo(tmp_path / "outside")

    app = create_app(api_token="secret-token", allowed_workspace_root=workspace)
    client = TestClient(app)

    payload = {
        "repo_root": str(repo_root),
        "events": [
            {
                "event_name": "order_created",
                "properties": {"order_id": "o_1", "amount_cents": 250},
            },
            {
                "event_name": "extra_runtime_event",
                "properties": {"foo": "bar"},
            },
        ],
    }

    unauth_resp = client.post("/v1/telemetry/verify", json=payload)
    assert unauth_resp.status_code == 401

    outside_resp = client.post(
        "/v1/telemetry/verify",
        json={"repo_root": str(outside), "events": []},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert outside_resp.status_code == 403

    ok_resp = client.post(
        "/v1/telemetry/verify",
        json=payload,
        headers={"Authorization": "Bearer secret-token"},
    )
    assert ok_resp.status_code == 200
    report = TelemetryVerificationReport.model_validate(ok_resp.json())
    assert report.total_code_events == 1
    assert report.matched_events == 1
    assert [item.event_name for item in report.items] == [
        "order_created",
        "extra_runtime_event",
    ]
    assert report.items[0].status == "matched"
    assert report.items[1].status == "unindexed_event"


def test_dashboard_endpoint_401_403_and_200(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    repo_root = _create_sample_repo(workspace / "repo")
    outside = _create_sample_repo(tmp_path / "outside")

    app = create_app(api_token="secret-token", allowed_workspace_root=workspace)
    client = TestClient(app)

    unauth_resp = client.get("/v1/dashboard", params={"repo_root": str(repo_root)})
    assert unauth_resp.status_code == 401

    wrong_auth_resp = client.get(
        "/v1/dashboard",
        params={"repo_root": str(repo_root)},
        headers={"X-PMCursor-Token": "wrong"},
    )
    assert wrong_auth_resp.status_code == 401

    outside_resp = client.get(
        "/v1/dashboard",
        params={"repo_root": str(outside)},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert outside_resp.status_code == 403

    ok_resp = client.get(
        "/v1/dashboard",
        params={"repo_root": str(repo_root), "prd_path": "PROJECT_SPEC.md"},
        headers={"Authorization": "Bearer secret-token"},
    )
    assert ok_resp.status_code == 200
    summary = OrgDashboardSummary.model_validate(ok_resp.json())
    assert summary.repo_root == str(repo_root.resolve())
    assert summary.models_count == 1
    assert summary.routes_count == 1
    assert summary.telemetry_count == 1
    assert summary.feature_flags_count == 1
    assert summary.scope_coverage_percent == 100.0
    assert summary.p0_checklist_items >= 0
    assert summary.status in {"DONE", "DONE_WITH_CONCERNS", "BLOCKED", "NEEDS_CONTEXT"}


def test_cli_telemetry_verify_json_and_ndjson(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _create_sample_repo(tmp_path / "repo")
    json_events = tmp_path / "events.json"
    json_events.write_text(
        json.dumps([{"event_name": "order_created", "properties": {"order_id": "1"}}]),
        encoding="utf-8",
    )

    rc_json = main(
        [
            "telemetry-verify",
            "--repo",
            str(repo_root),
            "--events-file",
            str(json_events),
            "--json",
        ]
    )
    assert rc_json == 0
    report = TelemetryVerificationReport.model_validate_json(capsys.readouterr().out)
    assert report.total_code_events == 1
    assert report.matched_events == 0
    assert report.items[0].status == "missing_properties"
    assert report.items[0].missing_properties == ["amount_cents"]

    ndjson_events = tmp_path / "events.ndjson"
    ndjson_events.write_text(
        json.dumps(
            {
                "event_name": "order_created",
                "properties": {"order_id": "1", "amount_cents": 100},
            }
        )
        + "\n",
        encoding="utf-8",
    )

    rc_md = main(
        [
            "telemetry-verify",
            "--repo",
            str(repo_root),
            "--events-file",
            str(ndjson_events),
        ]
    )
    assert rc_md == 0
    md_out = capsys.readouterr().out
    assert "## Telemetry Sample Verification" in md_out
    assert "`order_created`" in md_out
    assert "`matched`" in md_out


def test_cli_dashboard_json_and_markdown(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    repo_root = _create_sample_repo(tmp_path / "repo")

    rc_json = main(
        [
            "dashboard",
            "--repo",
            str(repo_root),
            "--prd",
            "PROJECT_SPEC.md",
            "--json",
        ]
    )
    assert rc_json == 0
    summary = OrgDashboardSummary.model_validate_json(capsys.readouterr().out)
    assert summary.models_count == 1
    assert summary.routes_count == 1
    assert summary.telemetry_count == 1
    assert summary.feature_flags_count == 1

    rc_md = main(
        [
            "dashboard",
            "--repo",
            str(repo_root),
            "--prd",
            "PROJECT_SPEC.md",
        ]
    )
    assert rc_md == 0
    md_out = capsys.readouterr().out
    assert "## PMCursor Org Alignment Dashboard" in md_out
    assert "1 models, 1 routes, 1 telemetry" in md_out


def test_new_top_level_exports() -> None:
    expected = [
        "ObservedTelemetryEvent",
        "PublishResult",
        "TelemetryDriftItem",
        "TelemetryVerificationReport",
        "publish_github_pr_comment",
        "publish_jira_comment",
        "publish_linear_comment",
        "verify_telemetry_samples",
    ]
    for name in expected:
        assert hasattr(pmcursor, name)
        assert name in pmcursor.__all__
    assert pmcursor.__all__ == sorted(pmcursor.__all__)
