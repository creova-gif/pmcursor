from __future__ import annotations

import re
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FeatureFlagProvider = Literal["launchdarkly", "statsig", "unleash", "generic"]

_MAX_FILE_BYTES = 2_097_152

_CODE_SUFFIXES = frozenset({".py", ".ts", ".tsx", ".js", ".jsx"})

_SKIP_DIRS = frozenset(
    {
        ".git",
        "node_modules",
        ".venv",
        "venv",
        "__pycache__",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }
)

_PROVIDER_PATTERNS: tuple[tuple[FeatureFlagProvider, re.Pattern[str]], ...] = (
    (
        "launchdarkly",
        re.compile(
            r"\b(?:bool_variation|string_variation|int_variation|variation)"
            r"""\(\s*["']([A-Za-z0-9_.-]+)["']"""
        ),
    ),
    (
        "statsig",
        re.compile(
            r"\b(?:check_gate|checkGate|useGate)"
            r"""\([^)]*?["']([A-Za-z0-9_.-]+)["']"""
        ),
    ),
    (
        "unleash",
        re.compile(
            r"\b(?:is_enabled|isEnabled|useFlag)"
            r"""\(\s*["']([A-Za-z0-9_.-]+)["']"""
        ),
    ),
    (
        "generic",
        re.compile(
            r"\b(?:feature_flag|get_flag|is_flag_enabled)"
            r"""\(\s*["']([A-Za-z0-9_.-]+)["']"""
        ),
    ),
)

_PRD_FLAG_RE = re.compile(
    r"(?im)(?:^|[\s`])(?:flag|feature_flag)\s*:\s*([A-Za-z0-9_.-]+)"
)
_ROLLBACK_RE = re.compile(r"rollback|kill[- ]switch", re.IGNORECASE)


class FeatureFlagContract(BaseModel):
    """A feature-flag evaluation site discovered in repository source code."""

    model_config = ConfigDict(frozen=True)

    flag_key: str
    provider: FeatureFlagProvider
    default_value: str | None = None
    file_path: str
    line: int = Field(ge=1)

    @property
    def citation(self) -> str:
        return f"{self.file_path}:{self.line}"


class FlagAuditReport(BaseModel):
    """Verification report comparing PRD flag & rollback specs against repo code."""

    model_config = ConfigDict(frozen=True)

    total_repo_flags: int
    referenced_flags: list[str]
    missing_prd_flags: list[str]
    undocumented_repo_flags: list[str]
    rollback_ready: bool
    markdown: str


def extract_feature_flags(repo_root: Path) -> list[FeatureFlagContract]:
    """Walk source files under ``repo_root`` and extract feature-flag call sites."""
    resolved_root = repo_root.resolve()
    if not resolved_root.is_dir():
        return []

    seen: set[tuple[str, FeatureFlagProvider, str, int]] = set()
    contracts: list[FeatureFlagContract] = []

    for path in sorted(resolved_root.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        if path.suffix not in _CODE_SUFFIXES:
            continue
        try:
            resolved_path = path.resolve()
            if not resolved_path.is_relative_to(resolved_root):
                continue
            rel_path_obj = resolved_path.relative_to(resolved_root)
        except (OSError, ValueError):
            continue

        if any(part in _SKIP_DIRS for part in rel_path_obj.parts[:-1]):
            continue

        try:
            if resolved_path.stat().st_size > _MAX_FILE_BYTES:
                continue
            source = resolved_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue

        rel_path = rel_path_obj.as_posix()
        for provider, pattern in _PROVIDER_PATTERNS:
            for match in pattern.finditer(source):
                flag_key = match.group(1)
                line = source.count("\n", 0, match.start()) + 1
                dedup_key = (flag_key, provider, rel_path, line)
                if dedup_key in seen:
                    continue
                seen.add(dedup_key)
                contracts.append(
                    FeatureFlagContract(
                        flag_key=flag_key,
                        provider=provider,
                        file_path=rel_path,
                        line=line,
                    )
                )

    contracts.sort(key=lambda c: (c.file_path, c.line, c.provider, c.flag_key))
    return contracts


def _is_flag_mentioned(flag_key: str, prd_markdown: str) -> bool:
    """Return True if ``flag_key`` appears as a standalone token in ``prd_markdown``."""
    pattern = re.compile(
        rf"(?<![A-Za-z0-9_.-]){re.escape(flag_key)}(?![A-Za-z0-9_.-])"
    )
    return pattern.search(prd_markdown) is not None


def _format_audit_markdown(
    *,
    total_repo_flags: int,
    referenced_flags: list[str],
    missing_prd_flags: list[str],
    undocumented_repo_flags: list[str],
    rollback_ready: bool,
) -> str:
    """Format a concise Markdown summary of the feature-flag & rollout audit."""
    lines = [
        "## Feature Flag & Rollout Audit",
        "",
        f"- **Repo flags detected:** {total_repo_flags}",
        f"- **Referenced in PRD:** {len(referenced_flags)}",
        f"- **Missing PRD flags (not in repo):** {len(missing_prd_flags)}",
        f"- **Undocumented repo flags:** {len(undocumented_repo_flags)}",
        f"- **Rollback ready:** {'Yes' if rollback_ready else 'No'}",
    ]

    if missing_prd_flags:
        lines.append("")
        lines.append("### Missing PRD Flags")
        for flag in missing_prd_flags:
            lines.append(f"- `{flag}`")

    if undocumented_repo_flags:
        lines.append("")
        lines.append("### Undocumented Repo Flags")
        for item in undocumented_repo_flags:
            lines.append(f"- {item}")

    if not rollback_ready:
        lines.append("")
        lines.append(
            "> **Warning:** No rollback plan or kill-switch documentation detected in PRD."
        )

    return "\n".join(lines) + "\n"


def audit_feature_flags_and_rollout(
    prd_markdown: str,
    repo_root: Path,
) -> FlagAuditReport:
    """Audit PRD feature-flag declarations and rollback readiness against ``repo_root``."""
    repo_flags = extract_feature_flags(repo_root)
    repo_flag_keys = {flag.flag_key for flag in repo_flags}

    prd_declared_flags = {
        match.group(1) for match in _PRD_FLAG_RE.finditer(prd_markdown)
    }

    referenced_set: set[str] = {
        key
        for key in repo_flag_keys
        if key in prd_declared_flags or _is_flag_mentioned(key, prd_markdown)
    }
    referenced_flags = sorted(referenced_set)
    missing_prd_flags = sorted(prd_declared_flags - repo_flag_keys)
    undocumented_repo_flags = [
        f"{flag.flag_key} ({flag.citation})"
        for flag in repo_flags
        if flag.flag_key not in referenced_set
    ]
    rollback_ready = _ROLLBACK_RE.search(prd_markdown) is not None

    markdown = _format_audit_markdown(
        total_repo_flags=len(repo_flags),
        referenced_flags=referenced_flags,
        missing_prd_flags=missing_prd_flags,
        undocumented_repo_flags=undocumented_repo_flags,
        rollback_ready=rollback_ready,
    )

    return FlagAuditReport(
        total_repo_flags=len(repo_flags),
        referenced_flags=referenced_flags,
        missing_prd_flags=missing_prd_flags,
        undocumented_repo_flags=undocumented_repo_flags,
        rollback_ready=rollback_ready,
        markdown=markdown,
    )
