"""Release consistency tests for package metadata, plugin manifests, and docs."""

from __future__ import annotations

import json
import tomllib
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent

REQUIRED_NON_EMPTY_FILES = (
    "README.md",
    "LICENSE",
    "CONTRIBUTING.md",
    "CHANGELOG.md",
    "Dockerfile",
    ".dockerignore",
    "docs/ROADMAP.md",
)


def _read_plugin_version(manifest_path: Path) -> str:
    data: object = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{manifest_path} must contain a JSON object"
    version: object = data.get("version")
    assert isinstance(version, str) and version.strip(), (
        f"{manifest_path} must define a non-empty string 'version'"
    )
    return version


def test_release_versions_match() -> None:
    pyproject_path = REPO_ROOT / "pyproject.toml"
    with pyproject_path.open("rb") as f:
        pyproject_data: object = tomllib.load(f)

    assert isinstance(pyproject_data, dict), "pyproject.toml must parse to a mapping"
    project_section: object = pyproject_data.get("project")
    assert isinstance(project_section, dict), "pyproject.toml must define [project]"
    pyproject_version: object = project_section.get("version")
    assert isinstance(pyproject_version, str) and pyproject_version.strip(), (
        "pyproject.toml [project].version must be a non-empty string"
    )

    cursor_version = _read_plugin_version(REPO_ROOT / ".cursor-plugin" / "plugin.json")
    claude_version = _read_plugin_version(REPO_ROOT / ".claude-plugin" / "plugin.json")

    assert cursor_version == pyproject_version, (
        f".cursor-plugin/plugin.json version ({cursor_version!r}) != "
        f"pyproject.toml version ({pyproject_version!r})"
    )
    assert claude_version == pyproject_version, (
        f".claude-plugin/plugin.json version ({claude_version!r}) != "
        f"pyproject.toml version ({pyproject_version!r})"
    )


def test_required_release_files_exist_and_non_empty() -> None:
    for rel_path in REQUIRED_NON_EMPTY_FILES:
        file_path = REPO_ROOT / rel_path
        assert file_path.is_file(), f"Required release file is missing: {rel_path}"
        content = file_path.read_text(encoding="utf-8").strip()
        assert content, f"Required release file is empty: {rel_path}"
