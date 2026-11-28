from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.tenancy import (
    OrgRegistry,
    OrgRegistryError,
    default_org_registry,
)


def _registry(tmp_path: Path) -> OrgRegistry:
    return OrgRegistry(tmp_path / "orgs.json")


def test_create_org_issues_prefixed_key_and_stores_hash_only(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    org, api_key = registry.create_org("Acme Corp")
    assert org.org_id == "acme-corp"
    assert api_key.startswith("pmk_")
    raw = (tmp_path / "orgs.json").read_text()
    assert api_key.split("_", 2)[2] not in raw
    assert org.keys[0].key_hash in raw


def test_create_org_rejects_duplicate_and_invalid_ids(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    registry.create_org("Acme", org_id="acme")
    with pytest.raises(OrgRegistryError):
        registry.create_org("Acme Again", org_id="acme")
    with pytest.raises(OrgRegistryError):
        registry.create_org("Bad Id", org_id="NO SPACES")
    with pytest.raises(OrgRegistryError):
        registry.create_org("")


def test_issue_key_and_revoke(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _org, first_key = registry.create_org("Acme", org_id="acme")
    second_key = registry.issue_key("acme", label="ci")
    assert second_key != first_key
    assert registry.resolve_key(second_key) == "acme"

    key_id = second_key.split("_")[1]
    assert registry.revoke_key(key_id) is True
    assert registry.resolve_key(second_key) is None
    assert registry.resolve_key(first_key) == "acme"
    assert registry.revoke_key("nonexistent") is False
    with pytest.raises(OrgRegistryError):
        registry.issue_key("missing-org")


def test_resolve_key_rejects_malformed_and_wrong_secret(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    key_id = api_key.split("_")[1]
    assert registry.resolve_key("not-a-key") is None
    assert registry.resolve_key(f"pmk_{key_id}_deadbeef") is None
    assert registry.resolve_key("pmk__secret") is None
    assert registry.resolve_key("pmk_zzzz_secret") is None


def test_resolve_key_stamps_last_used(tmp_path: Path) -> None:
    store = tmp_path / "orgs.json"
    registry = OrgRegistry(store)
    _, api_key = registry.create_org("Acme", org_id="acme")
    assert registry.resolve_key(api_key) == "acme"
    reloaded = OrgRegistry(store)
    org = reloaded.get_org("acme")
    assert org is not None
    assert org.keys[0].last_used_at is not None


def test_registry_persists_across_reloads(tmp_path: Path) -> None:
    store = tmp_path / "orgs.json"
    registry = OrgRegistry(store)
    registry.create_org("Acme", org_id="acme")
    registry.create_org("Beta", org_id="beta")
    reloaded = OrgRegistry(store)
    assert [o.org_id for o in reloaded.list_orgs()] == ["acme", "beta"]


def test_default_org_registry_env_gated(tmp_path: Path) -> None:
    assert default_org_registry({}) is None
    store = tmp_path / "orgs.json"
    registry = default_org_registry({"PMCURSOR_ORG_STORE": str(store)})
    assert registry is not None
    assert registry.store_path == store


def test_whoami_open_mode_without_auth() -> None:
    client = TestClient(create_app(api_token=""))
    body = client.get("/v1/whoami").json()
    assert body == {"authenticated": False, "auth": "open", "org_id": None}


def test_whoami_admin_token(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    client = TestClient(create_app(api_token="admintoken", org_registry=registry))
    resp = client.get(
        "/v1/whoami", headers={"Authorization": "Bearer admintoken"}
    )
    assert resp.status_code == 200
    assert resp.json() == {
        "authenticated": True,
        "auth": "admin",
        "org_id": None,
    }


def test_org_key_authenticates_and_binds(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(create_app(org_registry=registry))

    whoami = client.get("/v1/whoami", headers={"Authorization": f"Bearer {api_key}"})
    assert whoami.status_code == 200
    assert whoami.json() == {
        "authenticated": True,
        "auth": "org-key",
        "org_id": "acme",
    }

    # The org key authenticates real endpoints too — a bad key gets 401.
    denied = client.post(
        "/v1/index",
        json={"repo_root": "."},
        headers={"Authorization": "Bearer pmk_wrong_key"},
    )
    assert denied.status_code == 401


def test_org_key_via_x_pmcursor_token_header(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(create_app(org_registry=registry))
    resp = client.get("/v1/whoami", headers={"X-PMCursor-Token": api_key})
    assert resp.status_code == 200
    assert resp.json()["org_id"] == "acme"


def test_revoked_key_denied(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    registry.revoke_key(api_key.split("_")[1])
    client = TestClient(create_app(org_registry=registry))
    resp = client.get("/v1/whoami", headers={"Authorization": f"Bearer {api_key}"})
    assert resp.status_code == 401


def test_admin_and_org_keys_coexist(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(create_app(api_token="admintoken", org_registry=registry))
    admin = client.get("/v1/whoami", headers={"Authorization": "Bearer admintoken"})
    org = client.get("/v1/whoami", headers={"Authorization": f"Bearer {api_key}"})
    assert admin.json()["auth"] == "admin"
    assert org.json()["org_id"] == "acme"


def test_cli_orgs_lifecycle(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    from pmcursor.cli import main

    store = tmp_path / "orgs.json"
    assert (
        main(["orgs", "create", "--name", "Acme Corp", "--store", str(store)])
        == 0
    )
    out = capsys.readouterr().out
    api_key = next(
        line.split(": ", 1)[1]
        for line in out.splitlines()
        if "API key" in line
    )
    assert api_key.startswith("pmk_")

    assert main(["orgs", "list", "--store", str(store), "--json"]) == 0
    listed = json.loads(capsys.readouterr().out)
    assert listed["orgs"][0]["org_id"] == "acme-corp"

    assert (
        main(
            ["orgs", "issue-key", "--org-id", "acme-corp", "--store", str(store)]
        )
        == 0
    )
    key_id = api_key.split("_")[1]
    assert (
        main(
            ["orgs", "revoke-key", "--key-id", key_id, "--store", str(store)]
        )
        == 0
    )
    assert OrgRegistry(store).resolve_key(api_key) is None
