from __future__ import annotations

import base64
import io
import json
import sys
import types
import urllib.error
import urllib.request
from email.message import Message
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from api.server import create_app
from pmcursor.telemetry_connectors import (
    BigQueryConnector,
    ConnectorFetchError,
    LangfuseConnector,
    TelemetryConnectorResult,
    fetch_telemetry_events,
)
from pmcursor.telemetry_verify import (
    ObservedTelemetryEvent,
    TelemetryVerificationReport,
)


def _langfuse_payload(observations: list[dict[str, Any]], total_pages: int = 1) -> bytes:
    return json.dumps(
        {"data": observations, "meta": {"page": 1, "totalPages": total_pages}}
    ).encode("utf-8")


def _urlopen_returning(
    pages: list[bytes], calls: list[urllib.request.Request]
) -> Any:
    def fake_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> MagicMock:
        calls.append(req)
        resp = MagicMock()
        resp.read.return_value = pages[len(calls) - 1] if len(calls) <= len(pages) else pages[-1]
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        return resp

    return fake_urlopen


def test_langfuse_maps_observations_to_events(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[urllib.request.Request] = []
    payload = _langfuse_payload(
        [
            {
                "name": "checkout_started",
                "metadata": {"cart_id": "c1", "currency": "USD"},
            },
            {"name": "payment_failed", "input": {"error_code": "card_declined"}},
            {"name": None, "metadata": {}},  # dropped: no name
            {"metadata": {}},  # dropped: missing name
        ]
    )
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_returning([payload], calls))

    connector = LangfuseConnector(
        host="http://localhost:3000",
        public_key="pk-test",
        secret_key="sk-test",
        allow_private_urls=True,
    )
    events = connector.fetch_events(limit=50)

    assert len(events) == 2
    assert events[0].event_name == "checkout_started"
    assert events[0].properties == {"cart_id": "c1", "currency": "USD"}
    assert events[0].source_kind == "langfuse"
    assert events[1].event_name == "payment_failed"
    assert events[1].properties == {"error_code": "card_declined"}

    expected_auth = base64.b64encode(b"pk-test:sk-test").decode()
    assert calls[0].get_header("Authorization") == f"Basic {expected_auth}"
    assert calls[0].full_url.startswith("http://localhost:3000/api/public/observations?")


def test_langfuse_paginates_until_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[urllib.request.Request] = []
    page1 = json.dumps(
        {
            "data": [{"name": f"event_{i}", "metadata": {}} for i in range(3)],
            "meta": {"page": 1, "totalPages": 2},
        }
    ).encode("utf-8")
    page2 = json.dumps(
        {
            "data": [{"name": "event_last", "metadata": {}}],
            "meta": {"page": 2, "totalPages": 2},
        }
    ).encode("utf-8")
    monkeypatch.setattr(urllib.request, "urlopen", _urlopen_returning([page1, page2], calls))

    connector = LangfuseConnector(
        host="http://localhost:3000",
        public_key="pk",
        secret_key="sk",
        allow_private_urls=True,
    )
    events = connector.fetch_events(limit=10)

    assert len(events) == 4
    assert len(calls) == 2
    assert "page=2" in calls[1].full_url


def test_langfuse_missing_credentials_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("LANGFUSE_PUBLIC_KEY", raising=False)
    monkeypatch.delenv("LANGFUSE_SECRET_KEY", raising=False)
    with pytest.raises(ConnectorFetchError, match="LANGFUSE_PUBLIC_KEY"):
        LangfuseConnector()


def test_langfuse_uses_env_credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", _urlopen_returning([_langfuse_payload([])], calls)
    )
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-env")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-env")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:9999")

    connector = LangfuseConnector(allow_private_urls=True)
    connector.fetch_events(limit=5)

    assert calls[0].full_url.startswith("http://localhost:9999/api/public/observations?")


def test_langfuse_http_error_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail_urlopen(req: urllib.request.Request, timeout: float = 15.0) -> Any:
        raise urllib.error.HTTPError(
            req.full_url, 401, "Unauthorized", Message(), io.BytesIO(b"")
        )

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)
    connector = LangfuseConnector(
        host="http://localhost:3000",
        public_key="pk",
        secret_key="sk",
        allow_private_urls=True,
    )
    with pytest.raises(ConnectorFetchError, match="HTTP 401"):
        connector.fetch_events(limit=5)


def test_langfuse_rejects_private_host_by_default() -> None:
    connector = LangfuseConnector(
        host="http://localhost:3000", public_key="pk", secret_key="sk"
    )
    with pytest.raises(ValueError, match="https"):
        connector.fetch_events(limit=5)


def test_langfuse_non_json_response_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", _urlopen_returning([b"<html>nope</html>"], calls)
    )
    connector = LangfuseConnector(
        host="http://localhost:3000",
        public_key="pk",
        secret_key="sk",
        allow_private_urls=True,
    )
    with pytest.raises(ConnectorFetchError, match="non-JSON"):
        connector.fetch_events(limit=5)


def test_fetch_telemetry_events_unknown_source() -> None:
    with pytest.raises(ConnectorFetchError, match="Unsupported telemetry source"):
        fetch_telemetry_events("datadog")


def test_fetch_telemetry_events_warns_on_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    calls: list[urllib.request.Request] = []
    monkeypatch.setattr(
        urllib.request, "urlopen", _urlopen_returning([_langfuse_payload([])], calls)
    )
    result = fetch_telemetry_events(
        "langfuse",
        host="http://localhost:3000",
        public_key="pk",
        secret_key="sk",
        allow_private_urls=True,
    )
    assert isinstance(result, TelemetryConnectorResult)
    assert result.fetched_count == 0
    assert result.warnings


def test_bigquery_missing_target_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in ("PMCURSOR_BQ_PROJECT", "PMCURSOR_BQ_DATASET", "PMCURSOR_BQ_TABLE"):
        monkeypatch.delenv(var, raising=False)
    with pytest.raises(ConnectorFetchError, match="PMCURSOR_BQ_PROJECT"):
        BigQueryConnector()


def test_bigquery_missing_extra_raises() -> None:
    connector = BigQueryConnector(project="my-proj", dataset="ds", table="tbl")
    with pytest.raises(ConnectorFetchError, match=r"pmcursor\[bigquery\]"):
        connector.fetch_events(limit=5)


def _install_fake_bigquery(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict[str, Any]]
) -> None:
    google = types.ModuleType("google")
    cloud = types.ModuleType("google.cloud")
    bq = types.ModuleType("google.cloud.bigquery")

    class _ScalarQueryParameter:
        def __init__(self, name: str, kind: str, value: Any) -> None:
            self.name, self.kind, self.value = name, kind, value

    class _QueryJobConfig:
        def __init__(self, query_parameters: list[Any]) -> None:
            self.query_parameters = query_parameters

    class _Job:
        def result(self) -> list[dict[str, Any]]:
            return rows

    class _Client:
        def __init__(self, project: str) -> None:
            self.project = project
            self.queries: list[str] = []

        def query(self, query: str, job_config: Any) -> _Job:
            self.queries.append(query)
            return _Job()

    bq.Client = _Client  # type: ignore[attr-defined]
    bq.QueryJobConfig = _QueryJobConfig  # type: ignore[attr-defined]
    bq.ScalarQueryParameter = _ScalarQueryParameter  # type: ignore[attr-defined]
    cloud.bigquery = bq  # type: ignore[attr-defined]
    google.cloud = cloud  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "google", google)
    monkeypatch.setitem(sys.modules, "google.cloud", cloud)
    monkeypatch.setitem(sys.modules, "google.cloud.bigquery", bq)


def test_bigquery_maps_rows_to_events(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_bigquery(
        monkeypatch,
        [
            {"event_name": "checkout_started", "properties": '{"cart_id": "c1"}'},
            {"event_name": "refund_issued", "properties": {"refund_id": "r9"}},
            {"event_name": None, "properties": {}},
        ],
    )
    connector = BigQueryConnector(project="my-proj", dataset="ds", table="tbl")
    events = connector.fetch_events(limit=10)

    assert len(events) == 2
    assert events[0].event_name == "checkout_started"
    assert events[0].properties == {"cart_id": "c1"}
    assert events[0].source_kind == "bigquery"
    assert events[1].properties == {"refund_id": "r9"}


def test_bigquery_query_failure_wrapped(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_fake_bigquery(monkeypatch, [])
    connector = BigQueryConnector(project="my-proj", dataset="ds", table="tbl")

    import google.cloud.bigquery as bq

    class _BoomClient:
        def __init__(self, project: str) -> None:
            pass

        def query(self, query: str, job_config: Any) -> Any:
            raise RuntimeError("permission denied")

    monkeypatch.setattr(bq, "Client", _BoomClient)
    with pytest.raises(ConnectorFetchError, match="permission denied"):
        connector.fetch_events(limit=5)


def _telemetry_repo(base: Path) -> Path:
    app_dir = base / "app"
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "events.py").write_text(
        "from pmcursor import track_event\n\n"
        "@track_event('checkout_started', properties=['cart_id'])\n"
        "def checkout():\n"
        "    pass\n",
        encoding="utf-8",
    )
    return base


def test_api_telemetry_verify_with_source(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _telemetry_repo(tmp_path / "repo")
    fetched = TelemetryConnectorResult(
        source_kind="langfuse",
        fetched_count=1,
        events=[
            ObservedTelemetryEvent(
                event_name="checkout_started",
                properties={"cart_id": "c1"},
                source_kind="langfuse",
            )
        ],
    )

    calls: list[str] = []

    def fake_fetch(source_kind: str, *, limit: int, **params: Any) -> TelemetryConnectorResult:
        calls.append(source_kind)
        return fetched

    monkeypatch.setattr("api.server.fetch_telemetry_events", fake_fetch)

    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/v1/telemetry/verify",
        json={"repo_root": str(repo), "source": "langfuse", "limit": 25},
    )
    assert resp.status_code == 200
    report = TelemetryVerificationReport.model_validate(resp.json())
    assert calls == ["langfuse"]
    assert report.total_observed_events == 1


def test_api_telemetry_verify_requires_events_or_source(tmp_path: Path) -> None:
    repo = _telemetry_repo(tmp_path / "repo")
    app = create_app()
    client = TestClient(app)
    resp = client.post("/v1/telemetry/verify", json={"repo_root": str(repo)})
    assert resp.status_code == 422


def test_api_telemetry_verify_source_failure_is_502(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _telemetry_repo(tmp_path / "repo")

    def failing_fetch(source_kind: str, *, limit: int, **params: Any) -> Any:
        raise ConnectorFetchError("Langfuse credentials missing.")

    monkeypatch.setattr("api.server.fetch_telemetry_events", failing_fetch)
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/v1/telemetry/verify",
        json={"repo_root": str(repo), "source": "langfuse"},
    )
    assert resp.status_code == 502


def test_api_telemetry_verify_events_path_still_works(tmp_path: Path) -> None:
    repo = _telemetry_repo(tmp_path / "repo")
    app = create_app()
    client = TestClient(app)
    resp = client.post(
        "/v1/telemetry/verify",
        json={
            "repo_root": str(repo),
            "events": [{"event_name": "checkout_started", "properties": {}}],
        },
    )
    assert resp.status_code == 200
    report = TelemetryVerificationReport.model_validate(resp.json())
    assert report.total_observed_events == 1
