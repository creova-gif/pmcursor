from __future__ import annotations

import pytest

import pmcursor.cli as cli_module


def test_serve_without_server_extra_returns_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(cli_module, "_run_server", None)

    exit_code = cli_module.main(["serve"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "pmcursor[server]" in captured.err


@pytest.mark.parametrize("exc_type", [ValueError, RuntimeError])
def test_serve_error_from_run_server_returns_2(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    exc_type: type[Exception],
) -> None:
    def _failing_run_server(*, host: str, port: int) -> None:
        raise exc_type(f"cannot bind {host}:{port}")

    monkeypatch.setattr(cli_module, "_run_server", _failing_run_server)

    exit_code = cli_module.main(["serve", "--host", "0.0.0.0"])
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "Error: cannot bind 0.0.0.0:8000" in captured.err


def test_validate_plugin_succeeds_without_server_extra(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(cli_module, "_run_server", None)

    exit_code = cli_module.main(["validate-plugin", "--repo", "."])

    assert exit_code == 0
