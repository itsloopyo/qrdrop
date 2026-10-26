"""Browser tests for the delete, new-folder and rename actions in the listing."""

import tempfile
from collections.abc import Generator
from pathlib import Path

import pytest
from playwright.sync_api import Page, expect

from qrdrop.web.app import AppConfig, create_app
from tests.e2e.conftest import ServerInfo, UvicornTestServer, get_free_port


@pytest.fixture(scope="module")
def modify_server() -> Generator[ServerInfo, None, None]:
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        port = get_free_port()
        password = "test-e2e-password"
        config = AppConfig(
            root_dir=root,
            password=password,
            port=port,
            bind="127.0.0.1",
            show_hidden=False,
            session_timeout=3600,
            allow_upload=True,
            allow_delete=True,
            allow_modify=True,
        )
        server = UvicornTestServer(create_app(config), "127.0.0.1", port)
        server.start()
        yield ServerInfo(url=f"http://127.0.0.1:{port}", password=password, root_dir=root)
        server.stop()


@pytest.fixture
def page_on(page: Page, modify_server: ServerInfo) -> Page:
    page.goto(f"{modify_server.url}/?auth={modify_server.password}")
    page.wait_for_url(f"{modify_server.url}/")
    return page


def _row(page: Page, name: str):
    return page.locator(f'.file-row[data-path="{name}"]')


def _confirm_dialog(page: Page, value: str | None = None) -> None:
    dialog = page.locator("#app-dialog")
    expect(dialog).to_be_visible()
    if value is not None:
        page.fill("#app-dialog-input", value)
    page.click("#app-dialog-confirm")


class TestDelete:
    def test_success_removes_row_and_toasts(self, page_on: Page, modify_server: ServerInfo):
        (modify_server.root_dir / "gone.txt").write_text("x")
        page_on.reload()
        _row(page_on, "gone.txt").locator(".delete-btn").click()
        _confirm_dialog(page_on)
        expect(page_on.locator(".toast-success")).to_have_text("Deleted gone.txt")
        expect(_row(page_on, "gone.txt")).to_have_count(0)
        assert not (modify_server.root_dir / "gone.txt").exists()

    def test_failure_toasts_server_error(self, page_on: Page, modify_server: ServerInfo):
        target = modify_server.root_dir / "vanishing.txt"
        target.write_text("x")
        page_on.reload()
        _row(page_on, "vanishing.txt").locator(".delete-btn").click()
        target.unlink()
        _confirm_dialog(page_on)
        expect(page_on.locator(".toast-error")).to_have_text("Could not delete: Not found")
        expect(_row(page_on, "vanishing.txt")).to_have_count(1)


class TestNewFolder:
    def test_success_reloads_with_folder(self, page_on: Page, modify_server: ServerInfo):
        page_on.click("#new-folder-btn")
        _confirm_dialog(page_on, "  fresh  ")
        expect(_row(page_on, "fresh")).to_have_count(1)
        assert (modify_server.root_dir / "fresh").is_dir()

    def test_existing_name_toasts_error(self, page_on: Page, modify_server: ServerInfo):
        (modify_server.root_dir / "taken").mkdir()
        page_on.click("#new-folder-btn")
        _confirm_dialog(page_on, "taken")
        expect(page_on.locator(".toast-error")).to_have_text(
            "Could not create folder: 'taken' already exists"
        )


class TestRename:
    def test_success_reloads_with_new_name(self, page_on: Page, modify_server: ServerInfo):
        (modify_server.root_dir / "before.txt").write_text("x")
        page_on.reload()
        _row(page_on, "before.txt").locator(".rename-btn").click()
        _confirm_dialog(page_on, "after.txt")
        expect(_row(page_on, "after.txt")).to_have_count(1)
        assert (modify_server.root_dir / "after.txt").read_text() == "x"
        assert not (modify_server.root_dir / "before.txt").exists()

    def test_collision_toasts_error(self, page_on: Page, modify_server: ServerInfo):
        (modify_server.root_dir / "one.txt").write_text("1")
        (modify_server.root_dir / "two.txt").write_text("2")
        page_on.reload()
        _row(page_on, "one.txt").locator(".rename-btn").click()
        _confirm_dialog(page_on, "two.txt")
        expect(page_on.locator(".toast-error")).to_have_text(
            "Could not rename: 'two.txt' already exists"
        )


class TestUploadCheck:
    def test_existing_file_prompts_then_overwrites(
        self, page_on: Page, modify_server: ServerInfo, tmp_path: Path
    ):
        (modify_server.root_dir / "clash.txt").write_text("old")
        page_on.reload()
        upload = tmp_path / "clash.txt"
        upload.write_text("new")
        page_on.set_input_files("#upload-input", str(upload))
        expect(page_on.locator("#overwrite-file-list")).to_have_text("clash.txt")
        page_on.click("#overwrite-confirm-btn")
        expect(page_on.locator(".upload-file-success")).to_have_count(1)
        assert (modify_server.root_dir / "clash.txt").read_text() == "new"
