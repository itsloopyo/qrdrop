"""Writes from other pages on the same site, and framing by them."""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app


def _full_access_client(root: Path) -> TestClient:
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


class TestCrossOriginWrites:
    """Every port on a host is the same site, so SameSite=Lax alone lets a
    page from another server on this address write with the user's cookie."""

    def test_rename_from_another_port_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        client = _full_access_client(tmp_path)
        r = client.post(
            "/rename",
            content=b'{"path": "a.txt", "new_name": "b.txt"}',
            headers={"content-type": "text/plain", "origin": "http://testserver:9999"},
        )
        assert r.status_code == 403
        assert (tmp_path / "a.txt").exists()
        assert not (tmp_path / "b.txt").exists()

    def test_delete_from_another_origin_is_refused(self, tmp_path: Path) -> None:
        (tmp_path / "a.txt").write_text("x")
        client = _full_access_client(tmp_path)
        r = client.delete("/delete/a.txt", headers={"origin": "http://evil.example"})
        assert r.status_code == 403
        assert (tmp_path / "a.txt").exists()

    @pytest.mark.parametrize("origin", ["null", "http://[broken"])
    def test_opaque_or_malformed_origin_is_refused(self, tmp_path: Path, origin: str) -> None:
        client = _full_access_client(tmp_path)
        r = client.post("/mkdir", json={"path": "", "name": "d"}, headers={"origin": origin})
        assert r.status_code == 403
        assert not (tmp_path / "d").exists()

    def test_same_origin_write_is_allowed(self, tmp_path: Path) -> None:
        client = _full_access_client(tmp_path)
        r = client.post(
            "/mkdir", json={"path": "", "name": "d"}, headers={"origin": "http://testserver"}
        )
        assert r.status_code == 200
        assert (tmp_path / "d").is_dir()

    def test_write_without_origin_is_allowed(self, tmp_path: Path) -> None:
        client = _full_access_client(tmp_path)
        r = client.post("/mkdir", json={"path": "", "name": "d"})
        assert r.status_code == 200

    def test_cross_origin_read_is_not_refused(self, tmp_path: Path) -> None:
        client = _full_access_client(tmp_path)
        r = client.get("/", headers={"origin": "http://evil.example"})
        assert r.status_code == 200


class TestFraming:
    @pytest.mark.parametrize("path", ["/", "/login", "/static/style.css"])
    def test_responses_refuse_framing(self, client: TestClient, path: str) -> None:
        assert client.get(path).headers["x-frame-options"] == "DENY"
