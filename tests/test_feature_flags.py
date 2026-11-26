from __future__ import annotations

from pathlib import Path

from pmcursor.feature_flags import (
    FeatureFlagContract,
    FlagAuditReport,
    audit_feature_flags_and_rollout,
    extract_feature_flags,
)


def test_extract_feature_flags_all_providers_with_citations(tmp_path: Path) -> None:
    py_file = tmp_path / "src" / "flags.py"
    py_file.parent.mkdir(parents=True)
    py_file.write_text(
        (
            "def evaluate(ld_client, statsig, unleash, user):\n"
            '    ld_on = ld_client.bool_variation("checkout-v2", user, False)\n'
            '    sg_on = statsig.check_gate(user, "ai_search_gate")\n'
            '    ul_on = unleash.is_enabled("billing.proration")\n'
            '    gen_on = get_flag("legacy_banner")\n'
            "    return ld_on and sg_on and ul_on and gen_on\n"
        ),
        encoding="utf-8",
    )

    ts_file = tmp_path / "web" / "hooks.tsx"
    ts_file.parent.mkdir(parents=True)
    ts_file.write_text(
        (
            "export function useFeatureFlags() {\n"
            "  const gate = useGate('new-onboarding');\n"
            "  const flag = useFlag('dark-mode-ui');\n"
            '  const enabled = is_flag_enabled("beta_exports");\n'
            '  const ld = client.variation("ld-ts-flag", ctx, false);\n'
            "  return { gate, flag, enabled, ld };\n"
            "}\n"
        ),
        encoding="utf-8",
    )

    # Skipped directories should not be indexed
    ignored_file = tmp_path / "node_modules" / "pkg" / "index.js"
    ignored_file.parent.mkdir(parents=True)
    ignored_file.write_text('useFlag("should-be-ignored");', encoding="utf-8")

    flags = extract_feature_flags(tmp_path)

    assert all(isinstance(f, FeatureFlagContract) for f in flags)
    by_key = {(f.flag_key, f.provider): f.citation for f in flags}

    assert by_key == {
        ("checkout-v2", "launchdarkly"): "src/flags.py:2",
        ("ai_search_gate", "statsig"): "src/flags.py:3",
        ("billing.proration", "unleash"): "src/flags.py:4",
        ("legacy_banner", "generic"): "src/flags.py:5",
        ("new-onboarding", "statsig"): "web/hooks.tsx:2",
        ("dark-mode-ui", "unleash"): "web/hooks.tsx:3",
        ("beta_exports", "generic"): "web/hooks.tsx:4",
        ("ld-ts-flag", "launchdarkly"): "web/hooks.tsx:5",
    }


def test_extract_feature_flags_skips_oversized_files(tmp_path: Path) -> None:
    big_file = tmp_path / "huge.py"
    padding = "# " + ("x" * 2_097_200) + "\n"
    big_file.write_text(padding + 'get_flag("too_big")\n', encoding="utf-8")

    small_file = tmp_path / "small.py"
    small_file.write_text('feature_flag("just_right")\n', encoding="utf-8")

    flags = extract_feature_flags(tmp_path)
    assert [(f.flag_key, f.citation) for f in flags] == [("just_right", "small.py:1")]


def test_audit_feature_flags_missing_undocumented_and_rollback(tmp_path: Path) -> None:
    app_file = tmp_path / "app.py"
    app_file.write_text(
        (
            'if client.bool_variation("checkout-v2", user, False):\n'
            "    pass\n"
            'if is_enabled("secret_experiment"):\n'
            "    pass\n"
            'if checkGate("token_mentioned_flag"):\n'
            "    pass\n"
        ),
        encoding="utf-8",
    )

    prd_with_rollback = (
        "# Checkout V2 PRD\n"
        "\n"
        "flag: checkout-v2\n"
        "feature_flag: phantom_prd_flag\n"
        "Also integrates `token_mentioned_flag` for progressive delivery.\n"
        "\n"
        "## Rollout & Safety\n"
        "If error rates exceed 1%, trigger an immediate rollback via the kill switch.\n"
    )

    report = audit_feature_flags_and_rollout(prd_with_rollback, tmp_path)
    assert isinstance(report, FlagAuditReport)
    assert report.total_repo_flags == 3
    assert report.referenced_flags == ["checkout-v2", "token_mentioned_flag"]
    assert report.missing_prd_flags == ["phantom_prd_flag"]
    assert report.undocumented_repo_flags == ["secret_experiment (app.py:3)"]
    assert report.rollback_ready is True
    assert "phantom_prd_flag" in report.markdown
    assert "secret_experiment (app.py:3)" in report.markdown
    assert "Rollback ready:** Yes" in report.markdown

    prd_without_rollback = "# Minimal PRD\nflag: checkout-v2\n"
    report_no_rollback = audit_feature_flags_and_rollout(prd_without_rollback, tmp_path)
    assert report_no_rollback.rollback_ready is False
    assert "Rollback ready:** No" in report_no_rollback.markdown
