"""Tests for CLI argument parsing."""

import sys

import pytest

from qrdrop.cli import parse_args


def _run_with_argv(monkeypatch: pytest.MonkeyPatch, argv: list[str]):
    monkeypatch.delenv("QRDROP_PUBLIC_HOST", raising=False)
    monkeypatch.setattr(sys, "argv", ["qrdrop", *argv])
    return parse_args()


class TestParseArgs:
    def test_defaults(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, [])
        assert ns.port == 8000
        assert ns.bind == "0.0.0.0"
        assert ns.password is None
        assert ns.hide_dotfiles is False
        assert ns.upload is False
        assert ns.modify is False
        assert ns.timeout is None
        assert ns.quiet is False
        assert ns.public_host is None

    def test_port_short_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["-p", "9001"])
        assert ns.port == 9001

    def test_bind_short_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["-b", "127.0.0.1"])
        assert ns.bind == "127.0.0.1"

    def test_password_override(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--password", "abc-def-ghi"])
        assert ns.password == "abc-def-ghi"

    def test_hide_dotfiles_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--hide-dotfiles"])
        assert ns.hide_dotfiles is True

    def test_upload_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--upload"])
        assert ns.upload is True

    def test_modify_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--modify"])
        assert ns.modify is True

    def test_timeout(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--timeout", "120"])
        assert ns.timeout == 120

    def test_timeout_rejects_non_positive(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_with_argv(monkeypatch, ["--timeout", "0"])

    def test_quiet_flag(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--quiet"])
        assert ns.quiet is True

    def test_invalid_port_exits(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_with_argv(monkeypatch, ["--port", "not-a-number"])

    def test_public_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--public-host", "192.168.1.50"])
        assert ns.public_host == "192.168.1.50"

    def test_public_host_with_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        ns = _run_with_argv(monkeypatch, ["--public-host", "192.168.1.50:9000"])
        assert ns.public_host == "192.168.1.50:9000"

    def test_public_host_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["qrdrop"])
        monkeypatch.setenv("QRDROP_PUBLIC_HOST", "10.0.0.5")
        assert parse_args().public_host == "10.0.0.5"

    def test_public_host_flag_overrides_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(sys, "argv", ["qrdrop", "--public-host", "192.168.1.50"])
        monkeypatch.setenv("QRDROP_PUBLIC_HOST", "10.0.0.5")
        assert parse_args().public_host == "192.168.1.50"

    def test_public_host_rejects_missing_host(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_with_argv(monkeypatch, ["--public-host", ":9000"])

    def test_public_host_rejects_non_numeric_port(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit):
            _run_with_argv(monkeypatch, ["--public-host", "192.168.1.50:abc"])

    def test_version_exits_cleanly(self, monkeypatch: pytest.MonkeyPatch) -> None:
        with pytest.raises(SystemExit) as exc:
            _run_with_argv(monkeypatch, ["--version"])
        assert exc.value.code == 0
