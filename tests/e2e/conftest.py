"""Playwright fixtures for end-to-end testing."""

import socket
import tempfile
import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path

import pytest
import uvicorn

from qrdrop.web.app import AppConfig, create_app


def get_free_port() -> int:
    """Get a free port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        return s.getsockname()[1]


@dataclass
class ServerInfo:
    """Information about the running test server."""

    url: str
    password: str
    root_dir: Path


class UvicornTestServer:
    """A uvicorn server that runs in a background thread for testing."""

    def __init__(self, app, host: str, port: int):
        self.config = uvicorn.Config(app, host=host, port=port, log_level="warning")
        self.server = uvicorn.Server(self.config)
        self.thread = threading.Thread(target=self.server.run)

    def start(self) -> None:
        """Start the server in a background thread."""
        self.thread.start()
        # Wait for server to be ready
        while not self.server.started:
            time.sleep(0.01)

    def stop(self) -> None:
        """Stop the server."""
        self.server.should_exit = True
        self.thread.join(timeout=5)


@pytest.fixture(scope="session")
def e2e_temp_directory() -> Generator[Path, None, None]:
    """Create a temporary directory with test files for E2E tests.

    Yields:
        Path: The temporary directory path.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        tmppath = Path(tmpdir)

        # Create test files
        (tmppath / "hello.txt").write_text("Hello from E2E tests!")
        (tmppath / "readme.md").write_text("# Test README\n\nThis is a test file.")

        # Create a subdirectory with files
        subdir = tmppath / "documents"
        subdir.mkdir()
        (subdir / "report.txt").write_text("Test report content")

        yield tmppath


@pytest.fixture(scope="session")
def live_server(e2e_temp_directory: Path) -> Generator[ServerInfo, None, None]:
    """Start a live server for E2E testing.

    Args:
        e2e_temp_directory: The temporary directory with test files.

    Yields:
        ServerInfo: Information about the running server.
    """
    port = get_free_port()
    password = "test-e2e-password"

    config = AppConfig(
        root_dir=e2e_temp_directory,
        password=password,
        port=port,
        bind="127.0.0.1",
        show_hidden=False,
        session_timeout=3600,
    )

    app = create_app(config)
    server = UvicornTestServer(app, "127.0.0.1", port)
    server.start()

    yield ServerInfo(
        url=f"http://127.0.0.1:{port}",
        password=password,
        root_dir=e2e_temp_directory,
    )

    server.stop()


@pytest.fixture
def authenticated_page(page, live_server: ServerInfo):
    """Provide a Playwright page that is already authenticated.

    Args:
        page: Playwright page fixture.
        live_server: The running server info.

    Returns:
        The authenticated page.
    """
    # Navigate to login
    page.goto(f"{live_server.url}/login")

    # Fill in password and submit
    page.fill('input[name="password"]', live_server.password)
    page.click('button[type="submit"]')

    # Wait for redirect to complete
    page.wait_for_url(f"{live_server.url}/")

    return page
