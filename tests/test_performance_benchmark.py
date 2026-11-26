from __future__ import annotations

from pathlib import Path

from evals.benchmark import PerformanceBenchmarkResult, run_performance_benchmark


def test_run_performance_benchmark_reports_cache_speedup() -> None:
    result = run_performance_benchmark(Path("."))

    assert isinstance(result, PerformanceBenchmarkResult)
    assert result.eval_passed is True
    assert result.files_indexed > 0
    assert result.contracts_indexed > 0
    assert result.cold_index_ms > 0
    assert result.warm_cache_ms >= 0
    assert result.warm_cache_ms < result.cold_index_ms
    assert result.cache_speedup_ratio > 1.0
    assert result.drift_audit_ms >= 0
