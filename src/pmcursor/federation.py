from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from pmcursor.indexer import index_repository
from pmcursor.models import (
    ADRContract,
    ModelContract,
    RepoMap,
    RouteContract,
    TelemetryContract,
)


def _prefix_path(alias: str, path: str) -> str:
    clean_alias = alias.strip("/")
    if not clean_alias:
        return path
    return f"{clean_alias}/{path}"


def merge_repo_maps(
    named_repos: Sequence[tuple[str, RepoMap]],
    *,
    root_label: str = "federated",
) -> RepoMap:
    """Merge multiple named RepoMaps into a single federated RepoMap with alias-prefixed paths."""
    models: list[ModelContract] = []
    routes: list[RouteContract] = []
    telemetry: list[TelemetryContract] = []
    adrs: list[ADRContract] = []
    indexed_files: list[str] = []

    for alias, repo_map in named_repos:
        models.extend(
            m.model_copy(update={"file_path": _prefix_path(alias, m.file_path)})
            for m in repo_map.models
        )
        routes.extend(
            r.model_copy(update={"file_path": _prefix_path(alias, r.file_path)})
            for r in repo_map.routes
        )
        telemetry.extend(
            t.model_copy(update={"file_path": _prefix_path(alias, t.file_path)})
            for t in repo_map.telemetry
        )
        adrs.extend(
            a.model_copy(update={"file_path": _prefix_path(alias, a.file_path)})
            for a in repo_map.adrs
        )
        indexed_files.extend(
            _prefix_path(alias, path) for path in repo_map.indexed_files
        )

    return RepoMap(
        repo_root=root_label,
        models=models,
        routes=routes,
        telemetry=telemetry,
        adrs=adrs,
        indexed_files=sorted(set(indexed_files)),
    )


def index_federated_repos(named_roots: Sequence[tuple[str, Path]]) -> RepoMap:
    """Index multiple repositories and merge their RepoMaps under their respective aliases."""
    named_repos = [(alias, index_repository(root)) for alias, root in named_roots]
    return merge_repo_maps(named_repos)
