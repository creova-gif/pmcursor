from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
ACTION_YML = REPO_ROOT / ".github" / "actions" / "pmcursor-drift" / "action.yml"


def _read_action_yml() -> str:
    assert ACTION_YML.is_file(), f"Missing action.yml at {ACTION_YML}"
    return ACTION_YML.read_text(encoding="utf-8")


def test_action_yaml_metadata_and_inputs() -> None:
    content = _read_action_yml()

    assert re.search(r'^name:\s*"PMCursor Spec Drift Check"', content, re.MULTILINE)
    assert re.search(r"^description:\s*\S+", content, re.MULTILINE)

    for input_name in (
        "prd",
        "repo",
        "fail-on-drift",
        "python-version",
        "step-summary",
        "checklist",
    ):
        assert re.search(
            rf"^  {re.escape(input_name)}:\s*$", content, re.MULTILINE
        ), f"Missing input {input_name}"

    assert re.search(r'default:\s*"true"', content)
    assert re.search(r'default:\s*"false"', content)
    assert re.search(r'default:\s*"3\.12"', content)


def test_action_yaml_outputs_and_drift_step() -> None:
    content = _read_action_yml()

    assert re.search(r"^outputs:\s*$", content, re.MULTILINE)
    assert re.search(r"^  exit-code:\s*$", content, re.MULTILINE)
    assert "${{ steps.drift.outputs.exit_code }}" in content
    assert 'using: "composite"' in content
    assert "id: drift" in content
    assert "INPUT_STEP_SUMMARY: ${{ inputs.step-summary }}" in content
    assert "INPUT_CHECKLIST: ${{ inputs.checklist }}" in content
    assert 'ARGS=(drift --prd "$INPUT_PRD" --repo "$INPUT_REPO" --md)' in content
    assert "--fail-on-drift" in content
    assert "GITHUB_STEP_SUMMARY" in content
    assert "GITHUB_OUTPUT" in content
    assert 'pmcursor checklist --repo "$INPUT_REPO" --prd "$INPUT_PRD"' in content

    run_blocks = re.split(r"^\s+run:\s*\|?\s*$", content, flags=re.MULTILINE)[1:]
    for block in run_blocks:
        script_lines = []
        for line in block.splitlines():
            if re.match(r"^\s*-\s+(?:name|uses|id):", line):
                break
            script_lines.append(line)
        script = "\n".join(script_lines)
        assert "${{ inputs." not in script
        assert "${{ github.action_path }}" not in script
