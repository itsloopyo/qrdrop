"""Security regression tests for the audit pass.

Covers:
- Open-redirect protection on /login (?next=)
- Content-Disposition header sanitisation
- Symlink escape protection in archive collection
"""

import logging
import os
import sys
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.core.log_redaction import RedactAuthFilter, redact
from qrdrop.web.app import AppConfig
from qrdrop.web.handlers.archive import _collect_files
from qrdrop.web.handlers.auth import _safe_next_path
from qrdrop.web.handlers.files import content_disposition


class TestSafeNextPath:
    def test_none_returns_root(self) -> None:
        assert _safe_next_path(None) == "/"

    def test_empty_returns_root(self) -> None:
        assert _safe_next_path("") == "/"

    def test_relative_path_passes(self) -> None:
        assert _safe_next_path("/browse/foo") == "/browse/foo"

    @pytest.mark.parametrize(
        "candidate",
        [
            "//evil.example/",
            "/\\evil.example/",
            "https://evil.example/",
            "javascript:alert(1)",
            "evil.example",
            "/foo\r\nLocation: https://evil",
            "/foo\nbar",
        ],
    )
    def test_unsafe_candidates_collapse_to_root(self, candidate: str) -> None:
        assert _safe_next_path(candidate) == "/"


class TestLoginOpenRedirect:
    def test_post_with_external_next_redirects_to_root(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Login must not honour an attacker-supplied off-site `next`."""
        response = client.post(
            "/login",
            data={"password": app_config.password, "next": "//evil.example/"},
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_post_with_protocol_next_redirects_to_root(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        response = client.post(
            "/login",
            data={"password": app_config.password, "next": "https://evil.example/"},
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/"

    def test_post_with_safe_next_is_honoured(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        response = client.post(
            "/login",
            data={"password": app_config.password, "next": "/browse/subdir"},
        )
        assert response.status_code == 302
        assert response.headers["location"] == "/browse/subdir"


class TestContentDisposition:
    def test_strips_crlf(self) -> None:
        value = content_disposition("evil\r\nX-Injected: yes.txt", "attachment")
        assert "\r" not in value
        assert "\n" not in value

    def test_strips_quote(self) -> None:
        value = content_disposition('a"b.txt', "attachment")
        # Filename in the quoted ASCII fallback must not contain a raw quote.
        # The only legal quotes are the two wrapping the filename value.
        assert value.count('"') == 2

    def test_includes_utf8_filename_star(self) -> None:
        value = content_disposition("résumé.txt", "attachment")
        assert "filename*=UTF-8''" in value
        assert "r%C3%A9sum%C3%A9.txt" in value

    def test_blank_filename_falls_back_to_download(self) -> None:
        value = content_disposition("\r\n", "attachment")
        assert 'filename="download"' in value


class TestRedactAuth:
    @pytest.mark.parametrize(
        "raw,expected",
        [
            (
                "GET /?auth=apple-banana-cherry HTTP/1.1",
                "GET /?auth=<redacted> HTTP/1.1",
            ),
            (
                "GET /browse/x?foo=1&auth=p%C3%A4ss&bar=2 HTTP/1.1",
                "GET /browse/x?foo=1&auth=<redacted>&bar=2 HTTP/1.1",
            ),
            (
                "http://h:8000/?auth=secret",
                "http://h:8000/?auth=<redacted>",
            ),
        ],
    )
    def test_redact_strips_auth_value(self, raw: str, expected: str) -> None:
        assert redact(raw) == expected

    def test_redact_preserves_unrelated(self) -> None:
        s = "no secrets here"
        assert redact(s) == s

    def test_filter_rewrites_log_record(self) -> None:
        record = logging.LogRecord(
            name="uvicorn.access",
            level=logging.INFO,
            pathname=__file__,
            lineno=0,
            msg='%s - "%s" %s',
            args=("127.0.0.1", "GET /?auth=topsecret HTTP/1.1", 200),
            exc_info=None,
        )
        assert RedactAuthFilter().filter(record) is True
        assert "topsecret" not in record.getMessage()
        assert "auth=<redacted>" in record.getMessage()


@pytest.mark.skipif(
    sys.platform.startswith("win"),
    reason="Symlink creation typically requires elevation on Windows.",
)
class TestArchiveSymlinkEscape:
    def test_symlinks_outside_root_are_skipped(self, tmp_path: Path) -> None:
        # Create a victim file outside the served root.
        outside = tmp_path / "outside"
        outside.mkdir()
        secret = outside / "secret.txt"
        secret.write_text("PRIVATE")

        # Build the served root with a real file and a symlink pointing
        # outside the root.
        root = tmp_path / "root"
        root.mkdir()
        (root / "real.txt").write_text("public")
        try:
            os.symlink(secret, root / "link_to_secret.txt")
        except (OSError, NotImplementedError):
            pytest.skip("symlink creation not supported in this environment")

        files = _collect_files(root, [""])
        archive_paths = {archive_path for _, archive_path in files}

        # The legitimate file is included; the symlink target is not.
        assert any("real.txt" in p for p in archive_paths)
        assert not any("secret" in p for p in archive_paths)


class TestErrorMessagesDoNotLeakPaths:
    """OSError text embeds absolute server-side paths; responses must not."""

    @staticmethod
    def _modify_client(root: Path) -> TestClient:
        from qrdrop.web.app import create_app

        config = AppConfig(
            root_dir=root,
            password="pw",
            port=8000,
            bind="127.0.0.1",
            show_hidden=True,
            session_timeout=3600,
            allow_upload=True,
            allow_delete=True,
            allow_modify=True,
        )
        client = TestClient(create_app(config), follow_redirects=False)
        client.post("/login", data={"password": "pw", "next": "/"})
        return client

    def test_delete_failure_reports_reason_without_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import qrdrop.web.handlers.files as files_module

        (tmp_path / "stubborn").mkdir()

        def deny(path, *_args, **_kwargs):
            raise OSError(13, "Permission denied", str(path))

        monkeypatch.setattr(files_module.shutil, "rmtree", deny)
        client = self._modify_client(tmp_path)
        r = client.delete("/delete/stubborn")
        assert r.status_code == 500
        error = r.json()["error"]
        assert "Permission denied" in error
        assert str(tmp_path) not in error

    def test_mkdir_failure_reports_reason_without_absolute_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        client = self._modify_client(tmp_path)

        def deny(self, *_args, **_kwargs):
            raise OSError(13, "Permission denied", str(self))

        monkeypatch.setattr(Path, "mkdir", deny)
        r = client.post("/mkdir", json={"path": "", "name": "newdir"})
        assert r.status_code == 500
        error = r.json()["error"]
        assert "Permission denied" in error
        assert str(tmp_path) not in error


class TestLoginErrorReflection:
    def test_error_query_param_is_not_reflected(self, client: TestClient) -> None:
        """A crafted link must not inject attacker text into the login card."""
        r = client.get("/login?error=Account+locked+call+555-0100")
        assert r.status_code == 200
        assert "Account locked" not in r.text


class TestWindowsAlternateDataStreams:
    def test_colon_in_name_rejected_on_windows(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """On NTFS "file:stream" writes a hidden alternate data stream."""
        from qrdrop.web.handlers import _common

        monkeypatch.setattr(_common.os, "name", "nt")
        with pytest.raises(_common.RequestValidationError):
            _common.sanitize_name("evil:hidden.txt")

    def test_colon_in_name_allowed_on_posix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from qrdrop.web.handlers import _common

        monkeypatch.setattr(_common.os, "name", "posix")
        assert _common.sanitize_name("notes:v2.txt") == "notes:v2.txt"
