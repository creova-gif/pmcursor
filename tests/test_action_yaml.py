from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml  # type: ignore[import-untyped]

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = REPO_ROOT / ".github" / "actions" / "pmcursor-drift" / "action.yml"


def _load_action_yaml() -> dict[str, Any]:
    assert ACTION_YML.is_file(), f"Missing action.yml at {ACTION_YML}"
    loaded = yaml.safe_load(ACTION_YML.read_text(encoding="utf-8"))
    assert isinstance(loaded, dict), "action.yml must parse to a YAML mapping"
    return loaded


def test_action_yaml_metadata_and_inputs() -> None:
    data = _load_action_yaml()

    assert isinstance(data.get("name"), str) and data["name"]
    assert isinstance(data.get("description"), str) and data["description"]

    inputs = data.get("inputs")
    assert isinstance(inputs, dict)
    expected_inputs = {
        "prd",
        "repo",
        "fail-on-drift",
        "python-version",
        "step-summary",
        "checklist",
    }
    assert expected_inputs.issubset(inputs.keys())

    assert inputs["prd"]["required"] is True
    assert inputs["repo"]["required"] is False
    assert inputs["repo"]["default"] == "."
    assert inputs["fail-on-drift"]["required"] is False
    assert inputs["fail-on-drift"]["default"] == "true"
    assert inputs["python-version"]["required"] is False
    assert inputs["python-version"]["default"] == "3.12"
    assert inputs["step-summary"]["required"] is False
    assert inputs["step-summary"]["default"] == "true"
    assert inputs["checklist"]["required"] is False
    assert inputs["checklist"]["default"] == "false"


def test_action_yaml_outputs_and_drift_step() -> None:
    data = _load_action_yaml()

    outputs = data.get("outputs")
    assert isinstance(outputs, dict)
    assert "exit-code" in outputs
    assert outputs["exit-code"]["value"] == "${{ steps.drift.outputs.exit_code }}"
    assert isinstance(outputs["exit-code"].get("description"), str)

    runs = data.get("runs")
    assert isinstance(runs, dict)
    assert runs.get("using") == "composite"
    steps = runs.get("steps")
    assert isinstance(steps, list) and len(steps) >= 3

    drift_steps = [step for step in steps if isinstance(step, dict) and step.get("id") == "drift"]
    assert len(drift_steps) == 1
    drift_step = drift_steps[0]

    assert drift_step.get("shell") == "bash"
    env = drift_step.get("env")
    assert isinstance(env, dict)
    assert env.get("INPUT_PRD") == "${{ inputs.prd }}"
    assert env.get("INPUT_REPO") == "${{ inputs.repo }}"
    assert env.get("INPUT_FAIL_ON_DRIFT") == "${{ inputs.fail-on-drift }}"
    assert env.get("INPUT_STEP_SUMMARY") == "${{ inputs.step-summary }}"
    assert env.get("INPUT_CHECKLIST") == "${{ inputs.checklist }}"

    run_script = drift_step.get("run")
    assert isinstance(run_script, str)
    assert 'ARGS=(drift --prd "$INPUT_PRD" --repo "$INPUT_REPO" --md)' in run_script
    assert "pmcursor" in run_script
    assert "--fail-on-drift" in run_script
    assert "GITHUB_STEP_SUMMARY" in run_script
    assert "GITHUB_OUTPUT" in run_script
    assert 'pmcursor checklist --repo "$INPUT_REPO" --prd "$INPUT_PRD"' in run_script

    for step in steps:
        if isinstance(step, dict) and isinstance(step.get("run"), str):
            assert "${{ inputs." not in step["run"]
            assert "${{ github.action_path }}" not in step["run"]
