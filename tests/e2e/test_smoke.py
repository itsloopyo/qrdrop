"""Smoke tests to verify Playwright E2E infrastructure works."""

from playwright.sync_api import Page, expect


class TestSmoke:
    """Basic smoke tests to verify the E2E testing infrastructure."""

    def test_login_page_loads(self, page: Page, live_server):
        """Verify the login page loads correctly."""
        page.goto(f"{live_server.url}/login")

        # Verify page title or key elements
        expect(page.locator('input[name="password"]')).to_be_visible()
        expect(page.locator('button[type="submit"]')).to_be_visible()

    def test_login_flow(self, page: Page, live_server):
        """Verify login with correct password works."""
        page.goto(f"{live_server.url}/login")

        # Fill in password and submit
        page.fill('input[name="password"]', live_server.password)
        page.click('button[type="submit"]')

        # Should redirect to root and show file browser
        page.wait_for_url(f"{live_server.url}/")

        # Verify we can see test files (created in fixture)
        expect(page.locator("text=hello.txt")).to_be_visible()

    def test_authenticated_browse(self, authenticated_page: Page, live_server):  # noqa: ARG002
        """Verify browsing works after authentication."""
        # authenticated_page fixture already logged in
        # Verify we can see the file listing
        expect(authenticated_page.locator("text=hello.txt")).to_be_visible()
        expect(authenticated_page.locator("text=documents")).to_be_visible()

    def test_unauthenticated_redirect(self, page: Page, live_server):
        """Verify unauthenticated requests redirect to login."""
        # Try to access root without authentication
        page.goto(f"{live_server.url}/")

        # Should redirect to login
        assert "/login" in page.url
