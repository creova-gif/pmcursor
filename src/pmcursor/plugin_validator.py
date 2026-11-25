from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from pmcursor.models import PluginValidationResult

KEBAB_NAME_RE = re.compile(r"^[a-z0-9]([a-z0-9.-]*[a-z0-9])?$")
SEMVER_RE = re.compile(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:-[0-9A-Za-z.-]+)?$"
)


def _has_frontmatter(path: Path, required_keys: tuple[str, ...]) -> tuple[bool, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError as exc:
        return False, f"Cannot read {path.name}: {exc}"
    if not text.startswith("---\n"):
        return False, f"{path.as_posix()} is missing YAML frontmatter opening '---'"
    end_idx = text.find("\n---", 4)
    if end_idx == -1:
        return False, f"{path.as_posix()} is missing YAML frontmatter closing '---'"
    frontmatter_block = text[4:end_idx]
    for key in required_keys:
        if not re.search(rf"^{re.escape(key)}\s*:", frontmatter_block, re.MULTILINE):
            return False, f"{path.as_posix()} frontmatter is missing required key '{key}'"
    return True, ""


def _validate_relative_path(raw_path: str, field_name: str) -> list[str]:
    errors: list[str] = []
    if raw_path.startswith("/"):
        errors.append(f"Field '{field_name}' must be a relative path, got '{raw_path}'")
    if ".." in Path(raw_path).parts:
        errors.append(
            f"Field '{field_name}' must not traverse parent directories ('..'): '{raw_path}'"
        )
    return errors


def validate_plugin_manifests(repo_root: Path) -> PluginValidationResult:
    """Validate .cursor-plugin/plugin.json and .claude-plugin/plugin.json per cursor/plugins rules."""
    resolved = repo_root.resolve()
    errors: list[str] = []
    checked_components: list[str] = []

    cursor_manifest_path = resolved / ".cursor-plugin" / "plugin.json"
    claude_manifest_path = resolved / ".claude-plugin" / "plugin.json"

    if not cursor_manifest_path.is_file():
        return PluginValidationResult(
            valid=False,
            plugin_name="unknown",
            version="0.0.0",
            errors=[".cursor-plugin/plugin.json not found"],
            checked_components=[],
        )

    try:
        cursor_data: dict[str, Any] = json.loads(
            cursor_manifest_path.read_text(encoding="utf-8")
        )
    except (OSError, json.JSONDecodeError) as exc:
        return PluginValidationResult(
            valid=False,
            plugin_name="unknown",
            version="0.0.0",
            errors=[f"Failed to parse .cursor-plugin/plugin.json: {exc}"],
            checked_components=[],
        )

    plugin_name = str(cursor_data.get("name", ""))
    version = str(cursor_data.get("version", ""))

    if not plugin_name or not KEBAB_NAME_RE.match(plugin_name):
        errors.append(
            f"Invalid plugin name '{plugin_name}' in .cursor-plugin/plugin.json (must be lowercase kebab-case)"
        )
    if not version or not SEMVER_RE.match(version):
        errors.append(
            f"Invalid semantic version '{version}' in .cursor-plugin/plugin.json"
        )

    if claude_manifest_path.is_file():
        try:
            claude_data: dict[str, Any] = json.loads(
                claude_manifest_path.read_text(encoding="utf-8")
            )
            claude_name = str(claude_data.get("name", ""))
            claude_version = str(claude_data.get("version", ""))
            if claude_name != plugin_name:
                errors.append(
                    f"Plugin name mismatch: .cursor-plugin has '{plugin_name}' vs .claude-plugin '{claude_name}'"
                )
            if claude_version != version:
                errors.append(
                    f"Plugin version mismatch: .cursor-plugin has '{version}' vs .claude-plugin '{claude_version}'"
                )
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"Failed to parse .claude-plugin/plugin.json: {exc}")

    component_specs: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        ("skills", "SKILL.md", ("name", "description")),
        ("agents", "*.md", ("name", "description")),
        ("rules", "*.mdc", ("description",)),
    )

    for comp_key, pattern, req_keys in component_specs:
        raw_val = cursor_data.get(comp_key)
        if not isinstance(raw_val, str):
            continue
        errors.extend(_validate_relative_path(raw_val, comp_key))
        comp_dir = (resolved / raw_val).resolve()
        if not comp_dir.exists():
            errors.append(f"Declared {comp_key} directory '{raw_val}' does not exist")
            continue

        matched_files = (
            sorted(comp_dir.rglob(pattern))
            if comp_key == "skills"
            else sorted(comp_dir.glob(pattern))
        )
        if not matched_files:
            errors.append(f"No {comp_key} files matching '{pattern}' found in '{raw_val}'")
            continue

        for file_path in matched_files:
            ok, err_msg = _has_frontmatter(file_path, req_keys)
            rel_file = file_path.relative_to(resolved).as_posix()
            checked_components.append(rel_file)
            if not ok:
                errors.append(err_msg)

    return PluginValidationResult(
        valid=len(errors) == 0,
        plugin_name=plugin_name or "unknown",
        version=version or "0.0.0",
        errors=errors,
        checked_components=checked_components,
    )
