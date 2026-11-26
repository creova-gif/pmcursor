from __future__ import annotations

from pathlib import Path

from pmcursor.checklists import generate_edge_case_checklist
from pmcursor.indexer import index_repository


def _write_sample_repo(tmp_path: Path) -> Path:
    (tmp_path / "schemas.py").write_text(
        "from pydantic import BaseModel\n\n"
        "class OrderCreate(BaseModel):\n"
        "    order_id: str\n"
        "    amount_cents: int\n"
        "    coupon_code: str | None = None\n"
        "    notes: str | None = None\n"
        "    currency: str = 'USD'\n",
        encoding="utf-8",
    )
    (tmp_path / "routes.py").write_text(
        "from fastapi import FastAPI\n"
        "from schemas import OrderCreate\n\n"
        "app = FastAPI()\n\n"
        "@app.post('/orders')\n"
        "def create_order(payload: OrderCreate) -> dict[str, str]:\n"
        "    track_event('order_created', {'order_id': payload.order_id, 'amount': payload.amount_cents})\n"
        "    return {'id': payload.order_id}\n\n"
        "@app.get('/orders/{order_id}')\n"
        "def get_order(order_id: str) -> dict[str, str]:\n"
        "    return {'id': order_id}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_generate_checklist_emits_cited_schema_route_and_telemetry_items(
    tmp_path: Path,
) -> None:
    repo_root = _write_sample_repo(tmp_path)
    repo_map = index_repository(repo_root)

    checklist = generate_edge_case_checklist(repo_map, repo_root=repo_root)

    assert checklist.repo_root == str(repo_root)
    assert checklist.p0_count == 0
    assert checklist.total_items == len(checklist.items)
    assert checklist.total_items > 0

    schema_items = [i for i in checklist.items if i.category == "schema_validation"]
    route_items = [i for i in checklist.items if i.category == "api_auth_error"]
    telemetry_items = [i for i in checklist.items if i.category == "telemetry"]

    # OrderCreate has 5 fields; capped at 3 representative fields
    assert len(schema_items) == 3
    assert all(i.priority == "P1" for i in schema_items)
    assert any("optional" in i.scenario.lower() for i in schema_items)
    assert any("required" in i.scenario.lower() for i in schema_items)

    # POST /orders -> auth (401/403) + invalid payload (422); GET /orders/{order_id} -> 404
    assert len(route_items) == 3
    assert all(i.priority == "P1" for i in route_items)
    assert any("401" in i.expected_behavior and "403" in i.expected_behavior for i in route_items)
    assert any("422" in i.expected_behavior for i in route_items)
    assert any("404" in i.expected_behavior for i in route_items)

    assert len(telemetry_items) == 1
    assert telemetry_items[0].priority == "P2"
    assert telemetry_items[0].contract_name == "order_created"
    assert "order_id" in telemetry_items[0].scenario

    # Every citation must reference an actual indexed file and valid line number
    indexed_files = set(repo_map.indexed_files)
    for item in checklist.items:
        file_part, line_part = item.citation.rsplit(":", 1)
        assert file_part in indexed_files
        line_no = int(line_part)
        total_lines = len((repo_root / file_part).read_text(encoding="utf-8").splitlines())
        assert 1 <= line_no <= total_lines


def test_generate_checklist_includes_p0_spec_drift_when_prd_drifts(
    tmp_path: Path,
) -> None:
    repo_root = _write_sample_repo(tmp_path)
    repo_map = index_repository(repo_root)

    drifted_prd = (
        "## Contracts\n"
        "- `OrderCreate.amount_cents: str`\n"
        "- `telemetry: order_created(order_id, missing_prop)`\n"
    )

    checklist = generate_edge_case_checklist(
        repo_map,
        prd_markdown=drifted_prd,
        repo_root=repo_root,
    )

    drift_items = [i for i in checklist.items if i.category == "spec_drift"]
    assert checklist.p0_count == len(drift_items)
    assert checklist.p0_count >= 2
    assert all(i.priority == "P0" for i in drift_items)
    assert all(i.citation for i in drift_items)


def test_checklist_markdown_renders_valid_checkbox_lines_with_citations(
    tmp_path: Path,
) -> None:
    repo_root = _write_sample_repo(tmp_path)
    repo_map = index_repository(repo_root)

    checklist = generate_edge_case_checklist(repo_map, repo_root=repo_root)

    assert checklist.markdown.startswith("## PMCursor Edge-Case Checklist\n")
    checkbox_lines = [
        line for line in checklist.markdown.splitlines() if line.startswith("- [ ] ")
    ]
    assert len(checkbox_lines) == checklist.total_items
    for item, line in zip(checklist.items, checkbox_lines, strict=True):
        assert f"**[{item.priority}]**" in line
        assert f"[{item.category}]" in line
        assert f"**{item.contract_name}**" in line
        assert f"(`{item.citation}`)" in line
