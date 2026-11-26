from __future__ import annotations

import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any
from unittest.mock import MagicMock

import pytest

from pmcursor.models import RepoMap, TelemetryContract
from pmcursor.publisher import (
    publish_github_pr_comment,
    publish_jira_comment,
    publish_linear_comment,
)
from pmcursor.telemetry_verify import ObservedTelemetryEvent, verify_telemetry_samples


def _sample_repo_map() -> RepoMap:
    return RepoMap(
        repo_root="/tmp/repo",
        telemetry=[
            TelemetryContract(
                event_name="checkout_started",
                source_kind="posthog",
                properties=["cart_id", "currency"],
                file_path="src/checkout.py",
                line=42,
            ),
            TelemetryContract(
                event_name="payment_failed",
                source_kind="track_event",
                properties=["error_code", "gateway"],
                file_path="src/payments.py",
                line=88,
            ),
            TelemetryContract(
                event_name="refund_issued",
                source_kind="langfuse",
                properties=["refund_id"],
                file_path="src/refunds.py",
                line=15,
            ),
        ],
    )


def test_verify_telemetry_samples_statuses_and_citations() -> None:
    repo_map = _sample_repo_map()
    samples: list[ObservedTelemetryEvent | dict[str, Any]] = [
        ObservedTelemetryEvent(
            event_name="checkout_started",
            properties={"cart_id": "c1", "currency": "USD", "ab_variant": "B"},
            source_kind="posthog",
        ),
        {
            "event_name": "payment_failed",
            "properties": {"error_code": "card_declined"},
        },
        {
            "event_name": "legacy_ping",
            "properties": {"env": "prod", "region": "us-east"},
        },
    ]

    report = verify_telemetry_samples(repo_map, samples)

    assert report.total_code_events == 3
    assert report.total_observed_events == 3
    assert report.matched_events == 1

    by_event = {item.event_name: item for item in report.items}
    assert by_event["checkout_started"].status == "matched"
    assert by_event["checkout_started"].citation == "src/checkout.py:42"
    assert by_event["checkout_started"].missing_properties == []
    assert by_event["checkout_started"].extra_properties == ["ab_variant"]

    assert by_event["payment_failed"].status == "missing_properties"
    assert by_event["payment_failed"].citation == "src/payments.py:88"
    assert by_event["payment_failed"].missing_properties == ["gateway"]

    assert by_event["refund_issued"].status == "missing_in_samples"
    assert by_event["refund_issued"].citation == "src/refunds.py:15"
    assert by_event["refund_issued"].missing_properties == ["refund_id"]

    assert by_event["legacy_ping"].status == "unindexed_event"
    assert by_event["legacy_ping"].citation == "runtime:unindexed"
    assert by_event["legacy_ping"].extra_properties == ["env", "region"]

    assert "checkout_started" in report.markdown
    assert "runtime:unindexed" in report.markdown


def test_verify_telemetry_samples_unions_properties_across_samples() -> None:
    repo_map = RepoMap(
        repo_root="/tmp/repo",
        telemetry=[
            TelemetryContract(
                event_name="signup",
                source_kind="posthog",
                properties=["plan", "referrer"],
                file_path="src/auth.py",
                line=12,
            )
        ],
    )
    report = verify_telemetry_samples(
        repo_map,
        [
            {"event_name": "signup", "properties": {"plan": "pro"}},
            {"event_name": "signup", "properties": {"referrer": "google"}},
        ],
    )
    assert report.matched_events == 1
    assert report.items[0].status == "matched"
    assert report.items[0].citation == "src/auth.py:12"


def test_publisher_dry_run_makes_no_network_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    called = False

    def fail_urlopen(*args: Any, **kwargs: Any) -> Any:
        nonlocal called
        called = True
        raise AssertionError("urlopen should not be called in dry_run mode")

    monkeypatch.setattr(urllib.request, "urlopen", fail_urlopen)

    gh = publish_github_pr_comment("acme/app", 17, "Spec aligned", dry_run=True)
    assert gh.provider == "github"
    assert gh.dry_run is True
    assert gh.status_code == 0
    assert gh.target_id == "acme/app#17"
    assert gh.url == "https://api.github.com/repos/acme/app/issues/17/comments"

    lin = publish_linear_comment("ENG-42", "Drift detected", dry_run=True)
    assert lin.provider == "linear"
    assert lin.dry_run is True
    assert lin.status_code == 0
    assert lin.target_id == "ENG-42"

    jira = publish_jira_comment("https://acme.atlassian.net", "PM-9", "OK", dry_run=True)
    assert jira.provider == "jira"
    assert jira.dry_run is True
    assert jira.status_code == 0
    assert jira.url == "https://acme.atlassian.net/rest/api/2/issue/PM-9/comment"
    assert not called


def test_publisher_live_mocked_urlopen(monkeypatch: pytest.MonkeyPatch) -> None:
    captured: list[urllib.request.Request] = []

    def fake_urlopen(req: urllib.request.Request, timeout: int = 15) -> MagicMock:
        captured.append(req)
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        resp.status = 201
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    def _request_json(req: urllib.request.Request) -> dict[str, Any]:
        assert isinstance(req.data, bytes)
        loaded = json.loads(req.data)
        assert isinstance(loaded, dict)
        return loaded

    gh = publish_github_pr_comment("acme/app", 5, "LGTM", token="ghp_secret")
    assert gh.dry_run is False
    assert gh.status_code == 201
    assert captured[-1].get_header("Authorization") == "Bearer ghp_secret"
    assert _request_json(captured[-1]) == {"body": "LGTM"}

    lin = publish_linear_comment("LIN-1", "Check telemetry", api_key="lin_api_key")
    assert lin.status_code == 201
    assert captured[-1].get_header("Authorization") == "lin_api_key"
    lin_payload = _request_json(captured[-1])
    assert "commentCreate" in lin_payload["query"]
    assert lin_payload["variables"] == {"issueId": "LIN-1", "body": "Check telemetry"}

    jira = publish_jira_comment(
        "https://jira.example.com/", "PROJ-7", "Updated", bearer_token="jira_tok"
    )
    assert jira.status_code == 201
    assert jira.url == "https://jira.example.com/rest/api/2/issue/PROJ-7/comment"
    assert captured[-1].get_header("Authorization") == "Bearer jira_tok"
    assert _request_json(captured[-1]) == {"body": "Updated"}


def test_publisher_missing_token_and_invalid_url_raise() -> None:
    with pytest.raises(ValueError, match="token"):
        publish_github_pr_comment("acme/app", 1, "hi", token=None, dry_run=False)

    with pytest.raises(ValueError, match="token"):
        publish_linear_comment("ENG-1", "hi", api_key="   ", dry_run=False)

    with pytest.raises(ValueError, match="token"):
        publish_jira_comment("https://jira.example.com", "PROJ-1", "hi", bearer_token="")

    with pytest.raises(ValueError, match="https://"):
        publish_github_pr_comment("acme/app", 1, "hi", dry_run=True, api_base="ftp://bad.example")

    with pytest.raises(ValueError, match="https://"):
        publish_jira_comment("file:///etc/passwd", "PROJ-1", "hi", dry_run=True)


def _http_error(url: str, code: int, reason: str) -> urllib.error.HTTPError:
    return urllib.error.HTTPError(url=url, code=code, msg=reason, hdrs=Message(), fp=None)


def test_publisher_retries_transient_503_and_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def fake_urlopen(req: urllib.request.Request, timeout: int = 15) -> MagicMock:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise _http_error(req.full_url, 503, "Service Unavailable")
        resp = MagicMock()
        resp.__enter__.return_value = resp
        resp.__exit__.return_value = False
        resp.status = 201
        return resp

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    result = publish_github_pr_comment(
        "acme/app",
        42,
        "Retry worked",
        token="ghp_secret",
        max_retries=2,
        retry_delay_seconds=0.0,
    )
    assert attempts == 2
    assert result.status_code == 201


def test_publisher_does_not_retry_non_retryable_401(monkeypatch: pytest.MonkeyPatch) -> None:
    attempts = 0

    def fake_urlopen(req: urllib.request.Request, timeout: int = 15) -> MagicMock:
        nonlocal attempts
        attempts += 1
        raise _http_error(req.full_url, 401, "Unauthorized")

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)

    with pytest.raises(RuntimeError, match="HTTP 401") as exc_info:
        publish_linear_comment(
            "ENG-42",
            "Should fail immediately",
            api_key="lin_bad",
            max_retries=2,
            retry_delay_seconds=0.0,
        )

    assert attempts == 1
    assert isinstance(exc_info.value.__cause__, urllib.error.HTTPError)
    assert exc_info.value.__cause__.code == 401


def test_publisher_exhausting_max_retries_raises_final_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    http_attempts = 0

    def fail_http(req: urllib.request.Request, timeout: int = 15) -> MagicMock:
        nonlocal http_attempts
        http_attempts += 1
        raise _http_error(req.full_url, 503, f"Attempt {http_attempts}")

    monkeypatch.setattr(urllib.request, "urlopen", fail_http)

    with pytest.raises(RuntimeError, match="Attempt 3") as http_exc_info:
        publish_jira_comment(
            "https://jira.example.com",
            "PROJ-9",
            "Still failing",
            bearer_token="jira_tok",
            max_retries=2,
            retry_delay_seconds=0.0,
        )

    assert http_attempts == 3
    assert isinstance(http_exc_info.value.__cause__, urllib.error.HTTPError)
    assert http_exc_info.value.__cause__.code == 503

    url_attempts = 0

    def fail_url(req: urllib.request.Request, timeout: int = 15) -> MagicMock:
        nonlocal url_attempts
        url_attempts += 1
        raise urllib.error.URLError(f"Network down {url_attempts}")

    monkeypatch.setattr(urllib.request, "urlopen", fail_url)

    with pytest.raises(urllib.error.URLError, match="Network down 3"):
        publish_github_pr_comment(
            "acme/app",
            99,
            "Network down",
            token="ghp_secret",
            max_retries=2,
            retry_delay_seconds=0.0,
        )

    assert url_attempts == 3
