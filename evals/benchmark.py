from __future__ import annotations

from pmcursor.eval_runner import run_eval_benchmark

__all__ = ["run_eval_benchmark"]

if __name__ == "__main__":
    result = run_eval_benchmark()
    print(result.model_dump_json(indent=2))
    raise SystemExit(0 if result.passed else 1)
