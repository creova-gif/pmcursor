from __future__ import annotations

import base64
import json
import logging
import os
import re
import urllib.error
import urllib.request
from typing import Any, Protocol, runtime_checkable
from urllib.parse import urlencode

from pydantic import BaseModel, ConfigDict, Field

from pmcursor.models import TelemetrySourceKind
from pmcursor.publisher import _validate_outbound_url
from pmcursor.telemetry_verify import ObservedTelemetryEvent

logger = logging.getLogger(__name__)

_LANGFUSE_PAGE_SIZE = 100
_LANGFUSE_MAX_PAGES = 10
_BQ_PROJECT_ID = re.compile(r"[a-z][a-z0-9-]*[a-z0-9]")
_BQ_IDENTIFIER = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


def _validate_bq_part(kind: str, value: str, pattern: re.Pattern[str]) -> str:
    if not pattern.fullmatch(value):
        raise ConnectorFetchError(
            f"Invalid BigQuery {kind} {value!r}; "
            f"must match {pattern.pattern!r}. Refusing to build query."
        )
    return value


class ConnectorFetchError(RuntimeError):
    """Raised when a telemetry connector cannot fetch live samples."""


class TelemetryConnectorResult(BaseModel):
    """Result of fetching observed telemetry events from a live source."""

    model_config = ConfigDict(frozen=True)

    source_kind: TelemetrySourceKind
    fetched_count: int = Field(ge=0)
    events: list[ObservedTelemetryEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


@runtime_checkable
class TelemetryConnector(Protocol):
    """Fetches observed telemetry samples from a live source."""

    def fetch_events(self, *, limit: int) -> list[ObservedTelemetryEvent]:
        """Return up to `limit` observed events, most recent first."""
        ...


def _get_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout_seconds: float,
    allow_private_urls: bool,
) -> dict[str, Any]:
    _validate_outbound_url(url, allow_private_urls=allow_private_urls)
    req = urllib.request.Request(url, headers=headers, method="GET")  # noqa: S310
    try:
        # URL scheme & SSRF safety verified above via _validate_outbound_url.
        with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:  # noqa: S310
            raw = resp.read().decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ConnectorFetchError(
            f"Telemetry source returned HTTP {exc.code} for {url!r}"
        ) from exc
    except urllib.error.URLError as exc:
        raise ConnectorFetchError(
            f"Telemetry source unreachable for {url!r}: {exc.reason}"
        ) from exc
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConnectorFetchError(
            f"Telemetry source returned non-JSON response for {url!r}"
        ) from exc
    if not isinstance(payload, dict):
        raise ConnectorFetchError(
            f"Telemetry source returned unexpected payload type for {url!r}"
        )
    return payload


def _coerce_properties(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str) and raw.strip():
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return {"value": raw}
        return parsed if isinstance(parsed, dict) else {"value": parsed}
    return {}


class LangfuseConnector:
    """Fetch event observations from the Langfuse public API.

    Credentials come from parameters or the environment:
    `LANGFUSE_HOST` (default `https://cloud.langfuse.com`),
    `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`.
    """

    def __init__(
        self,
        *,
        host: str | None = None,
        public_key: str | None = None,
        secret_key: str | None = None,
        timeout_seconds: float = 15.0,
        allow_private_urls: bool = False,
    ) -> None:
        self._host = (
            host
            if host is not None
            else os.environ.get("LANGFUSE_HOST", "https://cloud.langfuse.com")
        ).rstrip("/")
        self._public_key = (
            public_key
            if public_key is not None
            else os.environ.get("LANGFUSE_PUBLIC_KEY", "")
        )
        self._secret_key = (
            secret_key
            if secret_key is not None
            else os.environ.get("LANGFUSE_SECRET_KEY", "")
        )
        if not self._public_key or not self._secret_key:
            raise ConnectorFetchError(
                "Langfuse credentials missing. Set LANGFUSE_PUBLIC_KEY and "
                "LANGFUSE_SECRET_KEY or pass public_key/secret_key."
            )
        self._timeout_seconds = timeout_seconds
        self._allow_private_urls = allow_private_urls

    def fetch_events(self, *, limit: int) -> list[ObservedTelemetryEvent]:
        if limit <= 0:
            return []
        auth = base64.b64encode(
            f"{self._public_key}:{self._secret_key}".encode()
        ).decode()
        headers = {"Authorization": f"Basic {auth}", "Accept": "application/json"}
        events: list[ObservedTelemetryEvent] = []
        for page in range(1, _LANGFUSE_MAX_PAGES + 1):
            page_size = min(_LANGFUSE_PAGE_SIZE, limit - len(events))
            if page_size <= 0:
                break
            query = urlencode({"type": "EVENT", "limit": page_size, "page": page})
            payload = _get_json(
                f"{self._host}/api/public/observations?{query}",
                headers=headers,
                timeout_seconds=self._timeout_seconds,
                allow_private_urls=self._allow_private_urls,
            )
            data = payload.get("data")
            if not isinstance(data, list) or not data:
                break
            for obs in data:
                if not isinstance(obs, dict):
                    continue
                name = obs.get("name")
                if not isinstance(name, str) or not name:
                    continue
                properties = _coerce_properties(
                    obs.get("metadata") or obs.get("input")
                )
                events.append(
                    ObservedTelemetryEvent(
                        event_name=name,
                        properties=properties,
                        source_kind="langfuse",
                    )
                )
                if len(events) >= limit:
                    return events
            meta = payload.get("meta")
            total_pages = meta.get("totalPages") if isinstance(meta, dict) else None
            if isinstance(total_pages, int) and page >= total_pages:
                break
        return events


class BigQueryConnector:
    """Fetch telemetry events from a BigQuery table via `pmcursor[bigquery]`.

    Configuration comes from parameters or the environment:
    `PMCURSOR_BQ_PROJECT`, `PMCURSOR_BQ_DATASET`, `PMCURSOR_BQ_TABLE`,
    `PMCURSOR_BQ_EVENT_COLUMN` (default `event_name`),
    `PMCURSOR_BQ_PROPERTIES_COLUMN` (default `properties`).
    Application Default Credentials (or `GOOGLE_APPLICATION_CREDENTIALS`)
    authenticate the client.
    """

    def __init__(
        self,
        *,
        project: str | None = None,
        dataset: str | None = None,
        table: str | None = None,
        event_column: str | None = None,
        properties_column: str | None = None,
    ) -> None:
        self._project = project or os.environ.get("PMCURSOR_BQ_PROJECT", "")
        self._dataset = dataset or os.environ.get("PMCURSOR_BQ_DATASET", "")
        self._table = table or os.environ.get("PMCURSOR_BQ_TABLE", "")
        self._event_column = event_column or os.environ.get(
            "PMCURSOR_BQ_EVENT_COLUMN", "event_name"
        )
        self._properties_column = properties_column or os.environ.get(
            "PMCURSOR_BQ_PROPERTIES_COLUMN", "properties"
        )
        if not (self._project and self._dataset and self._table):
            raise ConnectorFetchError(
                "BigQuery target missing. Set PMCURSOR_BQ_PROJECT, "
                "PMCURSOR_BQ_DATASET, and PMCURSOR_BQ_TABLE or pass "
                "project/dataset/table."
            )
        _validate_bq_part("project", self._project, _BQ_PROJECT_ID)
        for kind, value in (
            ("dataset", self._dataset),
            ("table", self._table),
            ("event_column", self._event_column),
            ("properties_column", self._properties_column),
        ):
            _validate_bq_part(kind, value, _BQ_IDENTIFIER)

    def fetch_events(self, *, limit: int) -> list[ObservedTelemetryEvent]:
        if limit <= 0:
            return []
        try:
            from google.cloud import bigquery
        except ModuleNotFoundError as exc:
            raise ConnectorFetchError(
                "google-cloud-bigquery is required for BigQuery connectors. "
                "Install with: pip install 'pmcursor[bigquery]'"
            ) from exc

        table_ref = f"`{self._project}.{self._dataset}.{self._table}`"
        # Table/column identifiers cannot be parameterized; all interpolated
        # parts are whitelist-validated in __init__ before this query is built.
        query = (
            f"SELECT `{self._event_column}` AS event_name, "  # noqa: S608
            f"`{self._properties_column}` AS properties "
            f"FROM {table_ref} LIMIT @limit"
        )
        client = bigquery.Client(project=self._project)
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ScalarQueryParameter("limit", "INT64", limit)
            ]
        )
        try:
            rows = client.query(query, job_config=job_config).result()
        except Exception as exc:
            raise ConnectorFetchError(
                f"BigQuery query failed for {table_ref}: {exc}"
            ) from exc

        events: list[ObservedTelemetryEvent] = []
        for row in rows:
            name = row["event_name"]
            if not isinstance(name, str) or not name:
                continue
            events.append(
                ObservedTelemetryEvent(
                    event_name=name,
                    properties=_coerce_properties(row["properties"]),
                    source_kind="bigquery",
                )
            )
        return events


def fetch_telemetry_events(
    source_kind: str,
    *,
    limit: int = 500,
    **params: Any,
) -> TelemetryConnectorResult:
    """Fetch observed events from a live telemetry source.

    `source_kind` is `langfuse` or `bigquery`. Extra keyword arguments are
    passed to the connector constructor (`host`, `project`, `table`,
    `allow_private_urls`, ...).
    """
    if source_kind == "langfuse":
        connector: TelemetryConnector = LangfuseConnector(**params)
    elif source_kind == "bigquery":
        connector = BigQueryConnector(**params)
    else:
        raise ConnectorFetchError(
            f"Unsupported telemetry source '{source_kind}'. "
            "Supported: langfuse, bigquery."
        )
    events = connector.fetch_events(limit=limit)
    warnings: list[str] = []
    if not events:
        warnings.append(
            f"Source '{source_kind}' returned zero events; verification will "
            "report every code event as missing_in_samples."
        )
    return TelemetryConnectorResult(
        source_kind=source_kind,  # type: ignore[arg-type]
        fetched_count=len(events),
        events=events,
        warnings=warnings,
    )
