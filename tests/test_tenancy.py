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


def test_peek_resolve_does_not_stamp(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    assert registry.resolve_key(api_key, record_use=False) == "acme"
    org = registry.get_org("acme")
    assert org is not None
    assert org.keys[0].last_used_at is None


def test_org_key_denied_on_admin_endpoints(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(create_app(org_registry=registry))
    headers = {"Authorization": f"Bearer {api_key}"}

    resp = client.post("/v1/cache/clear", headers=headers)
    assert resp.status_code == 403

    resp = client.get(
        "/v1/github-app/manifest",
        params={"webhook_url": "https://x.example.com/hook"},
        headers=headers,
    )
    assert resp.status_code == 403

    resp = client.post(
        "/v1/github-app/installations/123/token", headers=headers
    )
    assert resp.status_code == 403


def test_admin_token_still_reaches_admin_endpoints(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(create_app(api_token="admintoken", org_registry=registry))
    headers = {"Authorization": "Bearer admintoken"}
    resp = client.post("/v1/cache/clear", headers=headers)
    assert resp.status_code == 200
    # Org key on the same deployment is still 403'd on the admin route.
    denied = client.post(
        "/v1/cache/clear", headers={"Authorization": f"Bearer {api_key}"}
    )
    assert denied.status_code == 403


def test_org_scoped_index_cache(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, key_a = registry.create_org("Acme", org_id="acme")
    _, key_b = registry.create_org("Beta", org_id="beta")
    from pmcursor.mcp_server import RepoIndexCache

    cache = RepoIndexCache()
    client = TestClient(
        create_app(org_registry=registry, repo_cache=cache)
    )
    body = {"repo_root": "."}
    client.post("/v1/index", json=body, headers={"Authorization": f"Bearer {key_a}"})
    client.post("/v1/index", json=body, headers={"Authorization": f"Bearer {key_a}"})
    assert cache.size == 1
    client.post("/v1/index", json=body, headers={"Authorization": f"Bearer {key_b}"})
    assert cache.size == 2


def test_org_scoped_rate_limit_bucket(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, key_a = registry.create_org("Acme", org_id="acme")
    _, key_b = registry.create_org("Beta", org_id="beta")
    client = TestClient(
        create_app(org_registry=registry, rate_limit_per_minute=1)
    )
    first = client.get(
        "/v1/whoami", headers={"Authorization": f"Bearer {key_a}"}
    )
    second = client.get(
        "/v1/whoami", headers={"Authorization": f"Bearer {key_a}"}
    )
    assert first.status_code == 200
    assert second.status_code == 429
    # Org B has its own bucket — not starved by org A's limit.
    other = client.get(
        "/v1/whoami", headers={"Authorization": f"Bearer {key_b}"}
    )
    assert other.status_code == 200


def test_metrics_requires_admin_when_auth_configured(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(
        create_app(api_token="admintoken", org_registry=registry)
    )
    # Global counters span tenants — org keys and anonymous callers get nothing.
    assert client.get("/metrics").status_code == 401
    assert (
        client.get(
            "/metrics", headers={"Authorization": f"Bearer {api_key}"}
        ).status_code
        == 403
    )
    resp = client.get(
        "/metrics", headers={"Authorization": "Bearer admintoken"}
    )
    assert resp.status_code == 200
    assert "pmcursor_http_requests_total" in resp.text


def test_metrics_open_in_unauthenticated_mode() -> None:
    client = TestClient(create_app(api_token=""))
    assert client.get("/metrics").status_code == 200


def test_audit_log_events_and_no_secret_leakage(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    registry = _registry(tmp_path)
    client = TestClient(
        create_app(api_token="admintoken", org_registry=registry)
    )
    with caplog.at_level(logging.INFO, logger="pmcursor.audit"):
        _, api_key = registry.create_org("Acme", org_id="acme")
        key_id = api_key.split("_")[1]
        # auth_failure: bad token
        assert (
            client.post(
                "/v1/index",
                json={"repo_root": "."},
                headers={"Authorization": "Bearer wrong"},
            ).status_code
            == 401
        )
        # admin_denied: org key on admin-only endpoint
        assert (
            client.post(
                "/v1/cache/clear",
                headers={"Authorization": f"Bearer {api_key}"},
            ).status_code
            == 403
        )
        registry.revoke_key(key_id)

    text = caplog.text
    for event in (
        "event=org_created org_id=acme",
        "event=auth_failure",
        "event=admin_denied org_id=acme",
        "event=org_key_revoked org_id=acme",
    ):
        assert event in text, event
    # The plaintext key secret and the admin token must never reach audit logs.
    secret = api_key.split("_", 2)[2]
    assert secret not in text
    assert "admintoken" not in text


def test_audit_rate_limited_event(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    registry = _registry(tmp_path)
    _, api_key = registry.create_org("Acme", org_id="acme")
    client = TestClient(
        create_app(org_registry=registry, rate_limit_per_minute=1)
    )
    with caplog.at_level(logging.WARNING, logger="pmcursor.audit"):
        client.get("/v1/whoami", headers={"Authorization": f"Bearer {api_key}"})
        client.get("/v1/whoami", headers={"Authorization": f"Bearer {api_key}"})
    assert "event=rate_limited" in caplog.text
    assert "bucket=org" in caplog.text
