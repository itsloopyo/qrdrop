"""Tests for the CLI ``main()`` orchestration.

``parse_args`` is covered in ``test_cli.py``; this module locks in the wiring
that ``main()`` performs: port selection (Docker vs. host), password handling,
the ``--upload``/``--readonly`` permission implications, banner suppression, and the log
redaction filter that keeps the ``?auth=`` password out of uvicorn's logs.
"""

import sys
from pathlib import Path

import pytest

from qrdrop import cli


@pytest.fixture
def harness(monkeypatch: pytest.MonkeyPatch):
    """Patch every external collaborator ``main()`` reaches and capture wiring.

    Returns a dict that, after ``cli.main()`` runs, holds the ``AppConfig``
    passed to ``create_app`` and the keyword args passed to ``uvicorn.run``.
    """
    import qrdrop.core.network as network
    import qrdrop.core.password as password
    import qrdrop.core.qr as qr
    import qrdrop.core.terminal as terminal
    import qrdrop.web.app as app_module

    captured: dict = {"banner_calls": 0}

    monkeypatch.setattr(network, "find_available_port", lambda start: start + 1)
    monkeypatch.setattr(network, "get_local_ip", lambda: "192.168.1.50")
    monkeypatch.setattr(password, "generate_password", lambda: "generated-pass-word")
    monkeypatch.setattr(qr, "generate_qr_terminal", lambda url: f"QR<{url}>")

    def fake_banner(**kwargs):
        captured["banner_calls"] += 1
        captured["banner_kwargs"] = kwargs

    monkeypatch.setattr(terminal, "print_startup_banner", fake_banner)

    real_create_app = app_module.create_app

    def fake_create_app(config):
        captured["config"] = config
        # Return a real app so nothing downstream chokes on the type.
        return real_create_app(config)

    monkeypatch.setattr(app_module, "create_app", fake_create_app)

    import uvicorn

    def fake_run(app, **kwargs):
        captured["uvicorn_app"] = app
        captured["uvicorn_kwargs"] = kwargs

    monkeypatch.setattr(uvicorn, "run", fake_run)

    # Ensure DOCKER_CONTAINER is unset unless a test opts in.
    monkeypatch.delenv("DOCKER_CONTAINER", raising=False)
    monkeypatch.delenv("QRDROP_PUBLIC_HOST", raising=False)

    return captured


def _run_main(monkeypatch: pytest.MonkeyPatch, argv: list[str]) -> None:
    monkeypatch.setattr(sys, "argv", ["qrdrop", *argv])
    cli.main()


class TestPortSelection:
    def test_finds_available_port_outside_docker(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--port", "8000", "--quiet"])
        # fake find_available_port returns start + 1.
        assert harness["config"].port == 8001
        assert harness["uvicorn_kwargs"]["port"] == 8001

    def test_docker_uses_exact_port(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        monkeypatch.setenv("DOCKER_CONTAINER", "1")
        _run_main(monkeypatch, ["--port", "8000", "--quiet"])
        # No auto-increment inside Docker.
        assert harness["config"].port == 8000
        assert harness["uvicorn_kwargs"]["port"] == 8000


class TestPassword:
    def test_generates_password_when_not_provided(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["config"].password == "generated-pass-word"

    def test_uses_provided_password(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--password", "my-chosen-pw", "--quiet"])
        assert harness["config"].password == "my-chosen-pw"


class TestPermissions:
    def test_default_allows_upload_and_delete(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["config"].allow_upload is True
        assert harness["config"].allow_delete is True
        assert harness["config"].allow_modify is True

    def test_upload_flag_enables_upload_only(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--upload", "--quiet"])
        assert harness["config"].allow_upload is True
        assert harness["config"].allow_delete is False
        assert harness["config"].allow_modify is False

    def test_readonly_disables_all_writes(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--readonly", "--quiet"])
        assert harness["config"].allow_upload is False
        assert harness["config"].allow_delete is False
        assert harness["config"].allow_modify is False

    def test_hide_dotfiles_flag_disables_show_hidden(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--hide-dotfiles", "--quiet"])
        assert harness["config"].show_hidden is False

    def test_show_hidden_default_true(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["config"].show_hidden is True

    def test_timeout_default_none(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["config"].session_timeout is None

    def test_timeout_passed_through(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--timeout", "120", "--quiet"])
        assert harness["config"].session_timeout == 120

    def test_root_dir_is_cwd(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["config"].root_dir == Path.cwd()


class TestBanner:
    def test_quiet_suppresses_banner(self, monkeypatch: pytest.MonkeyPatch, harness: dict) -> None:
        _run_main(monkeypatch, ["--quiet"])
        assert harness["banner_calls"] == 0
        # Quiet mode runs uvicorn at the warning log level.
        assert harness["uvicorn_kwargs"]["log_level"] == "warning"

    def test_banner_printed_when_not_quiet(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--password", "abc-def", "--port", "8000"])
        assert harness["banner_calls"] == 1
        kwargs = harness["banner_kwargs"]
        assert kwargs["password"] == "abc-def"
        assert kwargs["network_url"] == "http://192.168.1.50:8001"
        assert kwargs["local_url"] == "http://localhost:8001"
        # The QR code is generated from an auth URL embedding the password.
        assert "auth=abc-def" in kwargs["qr_code"]
        assert harness["uvicorn_kwargs"]["log_level"] == "info"


class TestPublicHost:
    def test_overrides_detected_ip_in_banner_and_qr(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--public-host", "10.1.2.3", "--password", "abc-def"])
        kwargs = harness["banner_kwargs"]
        assert kwargs["network_url"] == "http://10.1.2.3:8001"
        assert kwargs["local_url"] == "http://localhost:8001"
        assert kwargs["qr_code"] == "QR<http://10.1.2.3:8001/?auth=abc-def>"

    def test_host_port_form_overrides_displayed_port(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        monkeypatch.setenv("DOCKER_CONTAINER", "1")
        _run_main(monkeypatch, ["--public-host", "10.1.2.3:9000", "--password", "abc-def"])
        kwargs = harness["banner_kwargs"]
        assert kwargs["network_url"] == "http://10.1.2.3:9000"
        assert kwargs["local_url"] == "http://localhost:9000"
        assert kwargs["qr_code"] == "QR<http://10.1.2.3:9000/?auth=abc-def>"
        # The display port is cosmetic; the server still binds the real port.
        assert harness["uvicorn_kwargs"]["port"] == 8000

    @pytest.mark.usefixtures("harness")
    def test_docker_without_public_host_warns(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("DOCKER_CONTAINER", "1")
        _run_main(monkeypatch, [])
        assert "--public-host" in capsys.readouterr().out

    @pytest.mark.usefixtures("harness")
    def test_docker_with_public_host_does_not_warn(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        monkeypatch.setenv("DOCKER_CONTAINER", "1")
        _run_main(monkeypatch, ["--public-host", "10.1.2.3"])
        assert "won't work" not in capsys.readouterr().out

    @pytest.mark.usefixtures("harness")
    def test_no_warning_outside_docker(
        self,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        _run_main(monkeypatch, [])
        assert "--public-host" not in capsys.readouterr().out


class TestServerWiring:
    def test_uvicorn_bound_to_requested_address(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--bind", "127.0.0.1", "--quiet"])
        assert harness["uvicorn_kwargs"]["host"] == "127.0.0.1"

    def test_log_config_wires_redaction_filter(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--quiet"])
        log_config = harness["uvicorn_kwargs"]["log_config"]

        # The redaction filter is registered...
        assert "redact_auth" in log_config["filters"]
        assert (
            log_config["filters"]["redact_auth"]["()"]
            == "qrdrop.core.log_redaction.RedactAuthFilter"
        )
        # ...and attached to every handler.
        assert log_config["handlers"], "expected uvicorn to define handlers"
        for handler in log_config["handlers"].values():
            assert "redact_auth" in handler["filters"]

    def test_log_config_is_a_copy_not_the_uvicorn_global(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        from uvicorn.config import LOGGING_CONFIG

        _run_main(monkeypatch, ["--quiet"])
        # The per-run config did get the filter wired in...
        assert "redact_auth" in harness["uvicorn_kwargs"]["log_config"]["filters"]
        # ...but mutating it must not pollute uvicorn's module global.
        assert "redact_auth" not in LOGGING_CONFIG.get("filters", {})


class TestAuthUrlEncoding:
    def test_password_is_percent_encoded_in_qr_url(
        self, monkeypatch: pytest.MonkeyPatch, harness: dict
    ) -> None:
        _run_main(monkeypatch, ["--password", "pass&word #1"])
        assert (
            harness["banner_kwargs"]["qr_code"]
            == "QR<http://192.168.1.50:8001/?auth=pass%26word%20%231>"
        )
