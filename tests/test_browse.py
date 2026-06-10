"""Tests for the directory browse handler."""

from pathlib import Path

from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig, create_app
from qrdrop.web.handlers.browse import BreadcrumbItem, build_breadcrumbs


class TestBuildBreadcrumbs:
    def test_root_yields_only_home(self) -> None:
        crumbs = build_breadcrumbs("")
        assert crumbs == [BreadcrumbItem(name="Home", path="")]

    def test_slash_yields_only_home(self) -> None:
        assert build_breadcrumbs("/") == [BreadcrumbItem(name="Home", path="")]

    def test_single_segment(self) -> None:
        crumbs = build_breadcrumbs("docs")
        assert crumbs == [
            BreadcrumbItem(name="Home", path=""),
            BreadcrumbItem(name="docs", path="docs"),
        ]

    def test_nested_segments_accumulate_paths(self) -> None:
        crumbs = build_breadcrumbs("a/b/c")
        assert [(c.name, c.path) for c in crumbs] == [
            ("Home", ""),
            ("a", "a"),
            ("b", "a/b"),
            ("c", "a/b/c"),
        ]

    def test_handles_leading_and_trailing_slashes(self) -> None:
        crumbs = build_breadcrumbs("/x/y/")
        assert [c.path for c in crumbs] == ["", "x", "x/y"]


class TestBrowseHandler:
    def test_root_listing_returns_html(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.get("/")
        assert response.status_code == 200
        assert "text/html" in response.headers["content-type"]
        assert b"test.txt" in response.content

    def test_nested_directory(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.get("/browse/subdir")
        assert response.status_code == 200
        assert b"nested.txt" in response.content

    def test_path_traversal_blocked_with_403(self, authenticated_client: TestClient) -> None:
        # Percent-encode the dot segments: a literal ../ is normalized away by
        # the HTTP client before it reaches the server, so it would never
        # exercise the traversal guard. %2e%2e%2f arrives intact and is
        # decoded by Starlette into the path param.
        response = authenticated_client.get("/browse/%2e%2e%2f%2e%2e%2fetc")
        assert response.status_code == 403

    def test_missing_directory_returns_404(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.get("/browse/does-not-exist")
        assert response.status_code == 404

    def test_file_path_redirects_to_view(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.get("/browse/test.txt")
        assert response.status_code == 302
        assert response.headers["location"] == "/view/test.txt"

    def test_hidden_file_not_visible_when_disabled(self, temp_directory: Path) -> None:
        config = AppConfig(
            root_dir=temp_directory,
            password="pw",
            port=8000,
            bind="127.0.0.1",
            show_hidden=False,
            session_timeout=3600,
        )
        app = create_app(config)
        client = TestClient(app, follow_redirects=False)
        client.post("/login", data={"password": "pw", "next": "/"})
        response = client.get("/")
        assert response.status_code == 200
        assert b".hidden" not in response.content

    def test_hidden_file_visible_when_enabled(self, authenticated_client: TestClient) -> None:
        response = authenticated_client.get("/")
        assert b".hidden" in response.content


class TestLinkEncoding:
    def test_reserved_characters_in_names_produce_encoded_links(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "file #1 50%.txt").write_text("tricky")
        r = authenticated_client.get("/")
        assert r.status_code == 200
        assert 'href="/view/file%20%231%2050%25.txt"' in r.text
        # Scripts read the raw path from data attributes; it must stay unencoded.
        assert 'data-path="file #1 50%.txt"' in r.text

        view = authenticated_client.get("/view/file%20%231%2050%25.txt")
        assert view.status_code == 200

    def test_browse_redirect_to_view_is_encoded(
        self, authenticated_client: TestClient, temp_directory: Path
    ) -> None:
        (temp_directory / "file #1.txt").write_text("x")
        r = authenticated_client.get("/browse/file%20%231.txt")
        assert r.status_code == 302
        assert r.headers["location"] == "/view/file%20%231.txt"
