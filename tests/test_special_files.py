"""FIFOs under the served root."""

import os
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app
from qrdrop.web.handlers.archive import _collect_files


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


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFOs are POSIX-only.")
class TestSpecialFiles:
    """Opening a FIFO blocks until the other end appears, which would pin a
    worker thread for good."""

    def test_view_fifo_is_not_found(self, tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "pipe")
        assert _full_access_client(tmp_path).get("/view/pipe").status_code == 404

    def test_download_fifo_is_not_found(self, tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "pipe")
        assert _full_access_client(tmp_path).get("/download/pipe").status_code == 404

    def test_upload_overwrite_onto_fifo_is_refused(self, tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "pipe")
        r = _full_access_client(tmp_path).post(
            "/upload", files={"file": ("pipe", b"data")}, data={"overwrite": "true"}
        )
        assert r.status_code == 409
        assert (tmp_path / "pipe").is_fifo()

    def test_archive_skips_fifo(self, tmp_path: Path) -> None:
        os.mkfifo(tmp_path / "pipe")
        (tmp_path / "real.txt").write_text("x")
        assert [a for _, a in _collect_files(tmp_path, [""])] == [f"{tmp_path.name}/real.txt"]
