from __future__ import annotations

import argparse
import time
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from pmcursor import RepoIndexCache, check_spec_drift
from pmcursor.eval_runner import run_eval_benchmark

__all__ = [
    "PerformanceBenchmarkResult",
    "run_eval_benchmark",
    "run_performance_benchmark",
]


class PerformanceBenchmarkResult(BaseModel):
    """Frozen performance and cache-speedup benchmark results."""

    model_config = ConfigDict(frozen=True)

    eval_passed: bool
    cold_index_ms: float
    warm_cache_ms: float
    cache_speedup_ratio: float
    drift_audit_ms: float
    files_indexed: int
    contracts_indexed: int


def run_performance_benchmark(
    repo_root: Path | None = None,
) -> PerformanceBenchmarkResult:
    """Measure eval correctness, cold/warm RepoIndexCache latency, and spec-drift audit time."""
    target_root = (repo_root or Path(".")).resolve()
    eval_res = run_eval_benchmark()

    cache = RepoIndexCache()

    cold_start = time.perf_counter()
    repo_map = cache.get_or_index(target_root)
    cold_index_ms = round((time.perf_counter() - cold_start) * 1000.0, 4)

    warm_start = time.perf_counter()
    cache.get_or_index(target_root)
    warm_cache_ms = round((time.perf_counter() - warm_start) * 1000.0, 4)

    spec_path = target_root / "PROJECT_SPEC.md"
    prd_text = spec_path.read_text(encoding="utf-8") if spec_path.is_file() else ""

    drift_start = time.perf_counter()
    check_spec_drift(prd_text, repo_map, repo_root=target_root)
    drift_audit_ms = round((time.perf_counter() - drift_start) * 1000.0, 4)

    cache_speedup_ratio = round(cold_index_ms / max(warm_cache_ms, 0.001), 2)
    contracts_indexed = (
        len(repo_map.models)
        + len(repo_map.routes)
        + len(repo_map.telemetry)
        + len(repo_map.adrs)
    )

    return PerformanceBenchmarkResult(
        eval_passed=eval_res.passed,
        cold_index_ms=cold_index_ms,
        warm_cache_ms=warm_cache_ms,
        cache_speedup_ratio=cache_speedup_ratio,
        drift_audit_ms=drift_audit_ms,
        files_indexed=len(repo_map.indexed_files),
        contracts_indexed=contracts_indexed,
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run PMCursor eval or performance benchmark.")
    parser.add_argument(
        "--perf",
        action="store_true",
        help="Run the performance and cache-speedup benchmark instead of the eval benchmark.",
    )
    args = parser.parse_args()

    if args.perf:
        perf_result = run_performance_benchmark()
        print(perf_result.model_dump_json(indent=2))
        raise SystemExit(0 if perf_result.eval_passed else 1)

    result = run_eval_benchmark()
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.passed else 1)
