from __future__ import annotations

from pathlib import Path

from pmcursor.models import (
    ADRContract,
    FieldContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)
from pmcursor.release_notes import (
    compute_scope_coverage,
    generate_release_notes_and_coverage,
)


def _sample_repo_map(repo_root: str = ".") -> RepoMap:
    return RepoMap(
        repo_root=repo_root,
        models=[
            ModelContract(
                name="UserAccount",
                file_path="src/models.py",
                line=10,
                base_classes=["BaseModel"],
                fields=[
                    FieldContract(name="id", type_annotation="str", line=11),
                    FieldContract(name="email", type_annotation="str", line=12),
                ],
            ),
            ModelContract(
                name="AuditLog",
                file_path="src/models.py",
                line=30,
                base_classes=["BaseModel"],
                fields=[
                    FieldContract(name="actor", type_annotation="str", line=31),
                ],
            ),
        ],
        routes=[
            RouteContract(
                method="POST",
                path="/v1/users",
                function_name="create_user",
                file_path="src/routes.py",
                line=15,
            ),
            RouteContract(
                method="DELETE",
                path="/v1/users/{user_id}",
                function_name="delete_user",
                file_path="src/routes.py",
                line=40,
            ),
        ],
        telemetry=[
            TelemetryContract(
                event_name="user.created",
                source_kind="track_event",
                properties=["user_id"],
                file_path="src/events.py",
                line=8,
            ),
            TelemetryContract(
                event_name="user.deleted",
                source_kind="track_event",
                properties=["user_id"],
                file_path="src/events.py",
                line=20,
            ),
        ],
        adrs=[
            ADRContract(
                adr_id="ADR-001",
                title="Use Pydantic v2 models",
                status="Accepted",
                file_path="docs/adr/001-pydantic.md",
                line=1,
            ),
            ADRContract(
                adr_id="ADR-002",
                title="Event bus partitioning",
                status="Proposed",
                file_path="docs/adr/002-events.md",
                line=1,
            ),
        ],
        indexed_files=[
            "src/models.py",
            "src/routes.py",
            "src/events.py",
            "docs/adr/001-pydantic.md",
            "docs/adr/002-events.md",
        ],
    )


def test_compute_scope_coverage_identifies_covered_and_uncovered_contracts() -> None:
    repo_map = _sample_repo_map()
    prd = """
# User Onboarding PRD
Uses `UserAccount` at `src/models.py:10` and `POST /v1/users` (`src/routes.py:15`).
Emits `telemetry: user.created(user_id)`.
Follows ADR-001.
"""

    coverage = compute_scope_coverage(prd, repo_map)

    assert coverage.total_repo_contracts == 8
    assert coverage.covered_contracts == 4
    assert coverage.coverage_percent == 50.0
    assert coverage.uncovered_models == ["AuditLog (src/models.py:30)"]
    assert coverage.uncovered_routes == ["DELETE /v1/users/{user_id} (src/routes.py:40)"]
    assert coverage.uncovered_telemetry == ["user.deleted (src/events.py:20)"]
    assert coverage.uncovered_adrs == ["ADR-002 (docs/adr/002-events.md:1)"]


def test_compute_scope_coverage_empty_repo_map() -> None:
    coverage = compute_scope_coverage("# Empty", RepoMap(repo_root="."))
    assert coverage.total_repo_contracts == 0
    assert coverage.covered_contracts == 0
    assert coverage.coverage_percent == 100.0
    assert coverage.uncovered_models == []
    assert coverage.uncovered_routes == []
    assert coverage.uncovered_telemetry == []
    assert coverage.uncovered_adrs == []


def test_generate_release_notes_and_coverage_with_overlapping_diff(
    tmp_path: Path,
) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "docs" / "adr").mkdir(parents=True)
    for rel in [
        "src/models.py",
        "src/routes.py",
        "src/events.py",
        "docs/adr/001-pydantic.md",
        "docs/adr/002-events.md",
    ]:
        (tmp_path / rel).write_text("\n" * 50, encoding="utf-8")

    repo_map = _sample_repo_map(str(tmp_path))
    prd = """
# User Onboarding PRD
- `UserAccount.id: str` (`src/models.py:11`)
- `POST /v1/users` (`src/routes.py:15`)
- `telemetry: user.created(user_id)`
- ADR-001
"""
    diff_text = """diff --git a/src/models.py b/src/models.py
--- a/src/models.py
+++ b/src/models.py
@@ -11,2 +11,3 @@
     id: str
     email: str
diff --git a/src/routes.py b/src/routes.py
--- a/src/routes.py
+++ b/src/routes.py
@@ -39,3 +39,3 @@
 def delete_user():
     pass
"""

    report = generate_release_notes_and_coverage(
        prd,
        diff_text,
        repo_map,
        prd_path="PRD.md",
        version="v1.2.0",
        repo_root=tmp_path,
    )

    assert report.version == "v1.2.0"
    assert report.prd_path == "PRD.md"
    assert report.changed_files_count == 2
    assert report.scope_coverage.coverage_percent == 50.0
    assert len(report.entries) == 2

    by_kind = {entry.contract_kind: entry for entry in report.entries}
    assert by_kind["model"].name == "UserAccount"
    assert by_kind["model"].citation == "src/models.py:10"
    assert by_kind["model"].covered_in_prd is True

    assert by_kind["route"].name == "DELETE /v1/users/{user_id}"
    assert by_kind["route"].citation == "src/routes.py:40"
    assert by_kind["route"].covered_in_prd is False

    assert "## Release Notes — v1.2.0" in report.markdown
    assert "4/8 (50.0%)" in report.markdown
    assert "### Changed Contracts" in report.markdown
    assert "src/models.py:10" in report.markdown
    assert "src/routes.py:40" in report.markdown
    assert "### Undocumented Code Contracts" in report.markdown
    assert "AuditLog (src/models.py:30)" in report.markdown


def test_generate_release_notes_and_coverage_empty_diff(tmp_path: Path) -> None:
    repo_map = _sample_repo_map(str(tmp_path))
    prd = "Covers `UserAccount`, `/v1/users`, `user.created`, and ADR-001."

    report = generate_release_notes_and_coverage(
        prd,
        "",
        repo_map,
        repo_root=tmp_path,
    )

    assert report.changed_files_count == 0
    assert report.entries == []
    assert report.scope_coverage.total_repo_contracts == 8
    assert report.scope_coverage.covered_contracts == 4
    assert report.scope_coverage.coverage_percent == 50.0
    assert "No indexed contracts changed in this diff." in report.markdown
