from __future__ import annotations

import json
from pathlib import Path

import pytest

from pmcursor.cli import main
from pmcursor.drift import check_spec_drift
from pmcursor.federation import index_federated_repos, merge_repo_maps
from pmcursor.models import (
    ADRContract,
    FieldContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)


def test_merge_repo_maps_prefixes_all_contracts() -> None:
    backend = RepoMap(
        repo_root="/tmp/backend",
        models=[
            ModelContract(
                name="User",
                file_path="app/models.py",
                line=5,
                fields=[FieldContract(name="id", type_annotation="int", line=6)],
            )
        ],
        routes=[
            RouteContract(
                method="GET",
                path="/users",
                function_name="list_users",
                file_path="app/routes.py",
                line=10,
            )
        ],
        telemetry=[
            TelemetryContract(
                event_name="user_created",
                source_kind="track_event",
                properties=["user_id"],
                file_path="app/events.py",
                line=3,
            )
        ],
        adrs=[
            ADRContract(
                adr_id="ADR-001",
                title="Use FastAPI",
                status="Accepted",
                file_path="docs/adr/001.md",
                line=1,
            )
        ],
        indexed_files=["app/models.py", "app/routes.py", "app/events.py", "docs/adr/001.md"],
    )
    frontend = RepoMap(
        repo_root="/tmp/frontend",
        models=[
            ModelContract(
                name="Session",
                file_path="src/types.ts",
                line=2,
            )
        ],
        indexed_files=["src/types.ts"],
    )

    merged = merge_repo_maps([("/api/", backend), ("web", frontend)], root_label="monorepo")

    assert merged.repo_root == "monorepo"
    assert [m.file_path for m in merged.models] == ["api/app/models.py", "web/src/types.ts"]
    assert merged.routes[0].file_path == "api/app/routes.py"
    assert merged.telemetry[0].file_path == "api/app/events.py"
    assert merged.adrs[0].file_path == "api/docs/adr/001.md"
    assert merged.indexed_files == [
        "api/app/events.py",
        "api/app/models.py",
        "api/app/routes.py",
        "api/docs/adr/001.md",
        "web/src/types.ts",
    ]


def test_index_federated_repos_and_cross_repo_drift(tmp_path: Path) -> None:
    api_dir = tmp_path / "api_repo"
    web_dir = tmp_path / "web_repo"
    api_dir.mkdir()
    web_dir.mkdir()

    (api_dir / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Order(BaseModel):\n    order_id: str\n",
        encoding="utf-8",
    )
    (web_dir / "routes.ts").write_text(
        "export interface CartItem { sku: string; }\n",
        encoding="utf-8",
    )

    federated = index_federated_repos([("api", api_dir), ("web", web_dir)])
    assert any(m.name == "Order" and m.file_path == "api/models.py" for m in federated.models)
    assert "api/models.py" in federated.indexed_files

    prd_md = (
        "# Cross-Repo Checkout\n\n"
        "See `api/models.py:3` for `Order.order_id: str`.\n\n"
        "## Acceptance Criteria\n- Order created.\n\n"
        "## Out of Scope\n- Refunds.\n\n"
        "## Rollback\n- Disable flag.\n"
    )
    report = check_spec_drift(prd_md, federated, prd_path="SPEC.md")
    assert report.fabricated_citations_count == 0
    assert report.findings == []


def test_cli_flags_and_federate(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    repo_a = tmp_path / "repo_a"
    repo_b = tmp_path / "repo_b"
    repo_a.mkdir()
    repo_b.mkdir()

    (repo_a / "flags.py").write_text(
        'enabled = ld_client.bool_variation("new_checkout", user, False)\n',
        encoding="utf-8",
    )
    (repo_a / "models.py").write_text(
        "from pydantic import BaseModel\n\nclass Invoice(BaseModel):\n    total: int\n",
        encoding="utf-8",
    )
    (repo_b / "worker.py").write_text(
        "from pydantic import BaseModel\n\nclass Job(BaseModel):\n    job_id: str\n",
        encoding="utf-8",
    )

    # flags without --prd
    rc = main(["flags", "--repo", str(repo_a), "--json"])
    assert rc == 0
    out = capsys.readouterr().out
    parsed_flags = json.loads(out)
    assert len(parsed_flags) == 1
    assert parsed_flags[0]["flag_key"] == "new_checkout"

    # flags with missing --prd -> exit 2
    rc_missing = main(["flags", "--repo", str(repo_a), "--prd", str(tmp_path / "missing.md")])
    assert rc_missing == 2
    capsys.readouterr()

    # flags with --prd
    prd_file = tmp_path / "PRD.md"
    prd_file.write_text(
        "# Checkout\nflag: new_checkout\n\n## Rollback\nRevert flag.\n",
        encoding="utf-8",
    )
    rc_audit = main(["flags", "--repo", str(repo_a), "--prd", str(prd_file), "--json"])
    assert rc_audit == 0
    audit_json = json.loads(capsys.readouterr().out)
    assert audit_json["rollback_ready"] is True

    # federate invalid format -> exit 2
    assert main(["federate", "--repos", "bad_entry"]) == 2
    capsys.readouterr()

    # federate missing dir -> exit 2
    assert main(["federate", "--repos", f"a={tmp_path / 'nope'}"]) == 2
    capsys.readouterr()

    # federate --json without --prd
    rc_fed = main(["federate", "--repos", f"a={repo_a}", f"b={repo_b}", "--json"])
    assert rc_fed == 0
    fed_json = json.loads(capsys.readouterr().out)
    model_paths = {m["name"]: m["file_path"] for m in fed_json["models"]}
    assert model_paths["Invoice"] == "a/models.py"
    assert model_paths["Job"] == "b/worker.py"

    # federate with --prd
    spec_file = tmp_path / "FED_SPEC.md"
    spec_file.write_text(
        "# Federated\nSee `a/models.py:3` for `Invoice.total: int` and `b/worker.py:3` for `Job.job_id: str`.\n",
        encoding="utf-8",
    )
    rc_fed_prd = main(
        ["federate", "--repos", f"a={repo_a}", f"b={repo_b}", "--prd", str(spec_file), "--json"]
    )
    assert rc_fed_prd == 0
    fed_drift = json.loads(capsys.readouterr().out)
    assert fed_drift["fabricated_citations_count"] == 0
