"""Tests for the delete handler."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app
from qrdrop.web.handlers import files as files_module


def _make_client(temp_directory: Path, *, allow_delete: bool) -> TestClient:
    config = AppConfig(
        root_dir=temp_directory,
        password="pw",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
        allow_delete=allow_delete,
    )
    app = create_app(config)
    client = TestClient(app, follow_redirects=False)
    client.post("/login", data={"password": "pw", "next": "/"})
    return client


class TestDelete:
    def test_delete_disabled_returns_403(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_delete=False)
        r = client.delete("/delete/test.txt")
        assert r.status_code == 403
        assert (temp_directory / "test.txt").exists()

    def test_delete_file(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/test.txt")
        assert r.status_code == 200
        assert r.json()["success"] is True
        assert not (temp_directory / "test.txt").exists()

    def test_delete_directory_recursive(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/subdir")
        assert r.status_code == 200
        assert not (temp_directory / "subdir").exists()

    def test_delete_missing_file_returns_404(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/does-not-exist")
        assert r.status_code == 404

    def test_delete_root_returns_403(self, temp_directory: Path) -> None:
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/")
        assert r.status_code == 403
        # Files still present
        assert (temp_directory / "test.txt").exists()

    def test_delete_path_traversal_returns_403(self, temp_directory: Path) -> None:
        # Percent-encoded dot segments survive client-side URL normalization,
        # so the request actually reaches the traversal guard.
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/%2e%2e%2f%2e%2e%2fetc%2fpasswd")
        assert r.status_code == 403

    def test_delete_oserror_returns_500(
        self, temp_directory: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom(_self: Path) -> None:
            raise OSError("permission denied")

        monkeypatch.setattr(files_module.Path, "unlink", boom)
        client = _make_client(temp_directory, allow_delete=True)
        r = client.delete("/delete/test.txt")
        assert r.status_code == 500
        body = r.json()
        assert body["success"] is False
        assert "permission denied" in body["error"]
