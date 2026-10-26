"""Characterization of request bodies with the wrong JSON shape.

These lock in current behaviour: each case below reaches an unhandled
exception inside the handler and comes back as a 500. They are recorded so
any change to that outcome is a deliberate one.
"""

from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app


@pytest.fixture
def client(temp_directory: Path) -> TestClient:
    config = AppConfig(
        root_dir=temp_directory,
        password="test-password",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
        allow_upload=True,
        allow_delete=True,
        allow_modify=True,
    )
    client = TestClient(create_app(config), follow_redirects=False, raise_server_exceptions=False)
    client.post("/login", data={"password": config.password, "next": "/"})
    return client


def test_upload_check_with_array_body_is_500(client: TestClient) -> None:
    assert client.post("/upload-check", json=[]).status_code == 500


def test_upload_check_with_non_string_path_is_500(client: TestClient) -> None:
    response = client.post("/upload-check", json={"path": 5, "filenames": []})
    assert response.status_code == 500


def test_mkdir_with_non_string_path_is_500(client: TestClient) -> None:
    assert client.post("/mkdir", json={"path": 5, "name": "x"}).status_code == 500


def test_rename_with_non_string_path_is_500(client: TestClient) -> None:
    assert client.post("/rename", json={"path": 5, "new_name": "x"}).status_code == 500


def test_mkdir_with_non_string_name_is_500(client: TestClient) -> None:
    assert client.post("/mkdir", json={"path": "", "name": 5}).status_code == 500


def test_archive_with_non_string_path_is_500(client: TestClient) -> None:
    response = client.post("/download-archive", data={"paths": "[5]", "format": "zip"})
    assert response.status_code == 500
