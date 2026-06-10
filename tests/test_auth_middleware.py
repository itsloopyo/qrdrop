"""Tests for authentication middleware, including QR code auto-login."""

import time

import pytest
from starlette.testclient import TestClient

from qrdrop.web.app import AppConfig


class TestAuthMiddleware:
    """Tests for the authentication middleware."""

    def test_unauthenticated_request_redirects_to_login(self, client: TestClient) -> None:
        """Unauthenticated requests should redirect to login page."""
        response = client.get("/")
        assert response.status_code == 302
        assert "/login" in response.headers["location"]

    def test_login_page_accessible_without_auth(self, client: TestClient) -> None:
        """Login page should be accessible without authentication."""
        response = client.get("/login", follow_redirects=True)
        assert response.status_code == 200

    def test_static_files_accessible_without_auth(self, client: TestClient) -> None:
        """Static files should be accessible without authentication."""
        response = client.get("/static/style.css")
        assert response.status_code == 200

    def test_successful_login_sets_session_cookie(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Successful login should set a session cookie."""
        response = client.post(
            "/login",
            data={"password": app_config.password, "next": "/"},
        )
        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies

    def test_invalid_password_shows_error(self, client: TestClient) -> None:
        """Invalid password should show an error message."""
        response = client.post(
            "/login",
            data={"password": "wrong-password", "next": "/"},
            follow_redirects=True,
        )
        assert response.status_code == 401
        assert b"Invalid password" in response.content


class TestQrCodeAutoLogin:
    """Tests for QR code auto-login functionality via URL auth parameter."""

    def test_auth_param_creates_session(self, client: TestClient, app_config: AppConfig) -> None:
        """Visiting URL with valid auth param should create session and redirect."""
        response = client.get(f"/?auth={app_config.password}")

        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies
        assert response.headers["location"] == "/"

    def test_auth_param_allows_access_after_redirect(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """After auth param login, should be able to access protected pages."""
        # First, authenticate via auth param
        client.get(f"/?auth={app_config.password}")

        # Now access protected page
        response = client.get("/", follow_redirects=True)
        assert response.status_code == 200

    def test_auth_param_with_path(self, client: TestClient, app_config: AppConfig) -> None:
        """Auth param should work with paths other than root."""
        response = client.get(f"/browse/subdir?auth={app_config.password}")

        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies
        assert response.headers["location"] == "/browse/subdir"

    def test_invalid_auth_param_redirects_to_login(self, client: TestClient) -> None:
        """Invalid auth param should redirect to login."""
        response = client.get("/?auth=wrong-password")

        assert response.status_code == 302
        assert "qrdrop_session" not in response.cookies
        assert "/login" in response.headers["location"]

    def test_non_ascii_auth_param_does_not_500(self, client: TestClient) -> None:
        """A non-ASCII ?auth= value must be rejected cleanly, not crash the app.

        Regression: comparing it with hmac.compare_digest as a str raised
        TypeError, letting any unauthenticated visitor trigger a 500.
        """
        response = client.get("/?auth=caf%C3%A9-na%C3%AFve")

        assert response.status_code == 302
        assert "qrdrop_session" not in response.cookies
        assert "/login" in response.headers["location"]

    def test_auth_param_with_special_characters(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Auth param should handle URL-encoded passwords correctly."""
        response = client.get(f"/?auth={app_config.password}")

        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies

    def test_session_persists_across_requests(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Session from auth param should persist across multiple requests."""
        # Authenticate
        client.get(f"/?auth={app_config.password}")

        # Make multiple requests - all should succeed
        response1 = client.get("/", follow_redirects=True)
        response2 = client.get("/browse/subdir", follow_redirects=True)

        assert response1.status_code == 200
        assert response2.status_code == 200

    def test_auth_param_with_existing_query_params(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Auth param should work alongside other query parameters."""
        response = client.get(f"/?auth={app_config.password}&other=value")

        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies

    def test_repeat_auth_param_reuses_existing_session(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        """Re-scanning the QR link must not mint a session per visit."""
        client.get(f"/?auth={app_config.password}")

        response = client.get(f"/?auth={app_config.password}")
        assert response.status_code == 200
        assert "qrdrop_session" not in response.cookies

    def test_malformed_cookie_header_redirects_to_login(self, client: TestClient) -> None:
        """A Cookie header with non-UTF-8 bytes must not crash the middleware."""
        response = client.get("/", headers={b"cookie": b"qrdrop_session=\xff\xfe"})

        assert response.status_code == 302
        assert "/login" in response.headers["location"]


class TestSessionManagement:
    """Tests for session management in middleware."""

    def test_logout_clears_session(self, authenticated_client: TestClient) -> None:
        """Logout must invalidate the server-side session, not just the cookie."""
        token = authenticated_client.cookies["qrdrop_session"]
        response = authenticated_client.get("/logout")

        assert response.status_code == 302
        assert "/login" in response.headers["location"]

        # Replaying the old cookie must not grant access.
        authenticated_client.cookies.set("qrdrop_session", token)
        replay = authenticated_client.get("/")
        assert replay.status_code == 302
        assert "/login" in replay.headers["location"]

    def test_invalid_session_token_redirects(self, client: TestClient) -> None:
        """Invalid session token should redirect to login."""
        client.cookies.set("qrdrop_session", "invalid-token")
        response = client.get("/")

        assert response.status_code == 302
        assert "/login" in response.headers["location"]

    def test_authenticated_access_to_browse(self, authenticated_client: TestClient) -> None:
        """Authenticated client should access browse page."""
        response = authenticated_client.get("/", follow_redirects=True)
        assert response.status_code == 200

    def test_redirect_preserves_original_path(self, client: TestClient) -> None:
        """Redirect to login should preserve the original requested path."""
        response = client.get("/browse/subdir")

        assert response.status_code == 302
        location = response.headers["location"]
        assert "/login" in location
        assert "next=" in location or "/browse/subdir" in location


class TestEncodedAuthParam:
    def test_percent_encoded_password_round_trips(self, tmp_path) -> None:
        """The QR URL percent-encodes the password; the middleware must decode it."""
        from qrdrop.web.app import create_app

        config = AppConfig(
            root_dir=tmp_path,
            password="pass&word #1",
            port=8000,
            bind="127.0.0.1",
            show_hidden=True,
            session_timeout=3600,
        )
        client = TestClient(create_app(config), follow_redirects=False)
        response = client.get("/?auth=pass%26word%20%231")
        assert response.status_code == 302
        assert "qrdrop_session" in response.cookies


class TestLoginThrottle:
    """Failed password attempts must be delayed; legitimate traffic must not."""

    DELAY = 0.25

    @pytest.fixture(autouse=True)
    def measurable_delay(self, monkeypatch: pytest.MonkeyPatch):
        from qrdrop.web import middleware

        monkeypatch.setattr(middleware, "LOGIN_FAILURE_DELAY_SECONDS", self.DELAY)

    def test_failed_login_post_is_delayed(self, client: TestClient) -> None:
        start = time.monotonic()
        r = client.post("/login", data={"password": "wrong", "next": "/"})
        elapsed = time.monotonic() - start
        assert r.status_code == 401
        assert elapsed >= self.DELAY

    def test_wrong_auth_param_is_delayed(self, client: TestClient) -> None:
        start = time.monotonic()
        r = client.get("/?auth=wrong-password")
        elapsed = time.monotonic() - start
        assert r.status_code == 302
        assert "/login" in r.headers["location"]
        assert elapsed >= self.DELAY

    def test_successful_login_is_not_delayed(
        self, client: TestClient, app_config: AppConfig
    ) -> None:
        start = time.monotonic()
        r = client.post("/login", data={"password": app_config.password, "next": "/"})
        elapsed = time.monotonic() - start
        assert r.status_code == 302
        assert elapsed < self.DELAY

    def test_valid_session_with_stale_auth_param_is_not_delayed(
        self, authenticated_client: TestClient
    ) -> None:
        start = time.monotonic()
        r = authenticated_client.get("/?auth=wrong-password")
        elapsed = time.monotonic() - start
        assert r.status_code == 200
        assert elapsed < self.DELAY
