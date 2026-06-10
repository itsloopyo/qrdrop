"""Pytest fixtures for qrdrop tests."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app


@pytest.fixture
def temp_directory() -> Generator[Path, None, None]:
    """Create a temporary directory with test files.

    Yields:
        Path: The temporary directory path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create some test files
        (tmppath / "test.txt").write_text("Hello, World!")
        (tmppath / "readme.md").write_text("# README\n\nThis is a test.")

        # Create a subdirectory with files
        subdir = tmppath / "subdir"
        subdir.mkdir()
        (subdir / "nested.txt").write_text("Nested content")

        # Create a hidden file
        (tmppath / ".hidden").write_text("Hidden file")

        yield tmppath


@pytest.fixture
def app_config(temp_directory: Path) -> AppConfig:
    """Create a test application configuration.

    Args:
        temp_directory: The temporary directory fixture.

    Returns:
        AppConfig: Configuration for testing.
    """
    return AppConfig(
        root_dir=temp_directory,
        password="test-password",
        port=8000,
        bind="127.0.0.1",
        show_hidden=True,
        session_timeout=3600,
    )


@pytest.fixture
def app(app_config: AppConfig):
    """Create a test application instance.

    Args:
        app_config: The test configuration fixture.

    Returns:
        The ASGI application.
    """
    return create_app(app_config)


@pytest.fixture
def client(app) -> TestClient:
    """Create a test client for the application.

    Args:
        app: The application fixture.

    Returns:
        TestClient: A Starlette test client.
    """
    return TestClient(app, follow_redirects=False)


@pytest.fixture
def authenticated_client(client: TestClient, app_config: AppConfig) -> TestClient:
    """Create a test client with an authenticated session.

    Args:
        client: The test client fixture.
        app_config: The test configuration.

    Returns:
        TestClient: A test client with valid session cookie.
    """
    # Login to get session cookie
    client.post(
        "/login",
        data={"password": app_config.password, "next": "/"},
    )

    # The client should now have the session cookie set
    return client


@pytest.fixture(autouse=True)
def _no_login_throttle(monkeypatch: pytest.MonkeyPatch):
    """Zero the brute-force delay so failed-login tests don't sleep.

    The throttle behavior itself is covered in test_auth_middleware, which
    overrides the delay to a measurable value.
    """
    from qrdrop.web import middleware

    monkeypatch.setattr(middleware, "LOGIN_FAILURE_DELAY_SECONDS", 0.0)
