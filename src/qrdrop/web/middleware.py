"""Authentication middleware for the QRDrop application.

Wraps the Starlette app to enforce authentication on all routes
except login and static files.
"""

import asyncio
from urllib.parse import quote, unquote

from starlette.applications import Starlette
from starlette.responses import RedirectResponse
from starlette.types import Receive, Scope, Send

from qrdrop.core.password import validate_password
from qrdrop.core.session import create_session, validate_session

SESSION_COOKIE_NAME = "qrdrop_session"
_SESSION_COOKIE_PREFIX = f"{SESSION_COOKIE_NAME}="

LOGIN_FAILURE_DELAY_SECONDS = 3.0
_failed_login_lock = asyncio.Lock()


async def throttle_failed_login() -> None:
    """Slow password brute-forcing to roughly one guess per delay window.

    Failed attempts are serialized through a single lock and each holds it
    for the full delay, so parallel connections cannot multiply the guess
    rate. Successful logins and valid-session requests never wait.
    """
    async with _failed_login_lock:
        await asyncio.sleep(LOGIN_FAILURE_DELAY_SECONDS)


class AuthMiddleware:
    """ASGI middleware that enforces authentication.

    Checks for a valid session cookie on every request.
    Redirects unauthenticated requests to /login.
    Allows /login and /static/* without authentication.
    """

    # Paths that don't require authentication - use frozenset for O(1) lookup
    EXEMPT_PATHS: frozenset[str] = frozenset({"/login", "/favicon.ico", "/health"})
    # Use tuple for prefix matching (faster iteration than list)
    EXEMPT_PREFIXES: tuple[str, ...] = ("/static/",)

    def __init__(self, app: Starlette) -> None:
        """Initialize the middleware.

        Args:
            app: The Starlette app to wrap, with config in app.state.config.
        """
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Handle an ASGI request.

        Args:
            scope: The ASGI scope.
            receive: The receive callable.
            send: The send callable.
        """
        # Only process HTTP requests
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        path = scope["path"]

        # Check if path is exempt from authentication
        if self._is_exempt_path(path):
            await self.app(scope, receive, send)
            return

        # Check session cookie first so re-visiting a ?auth= URL (a bookmarked
        # QR link) reuses the existing session instead of minting a new one.
        session_token = self._get_session_cookie(scope)

        if session_token and validate_session(session_token):
            # Valid session - proceed with request
            await self.app(scope, receive, send)
            return

        # Check for auto-login via URL parameter (for QR code convenience)
        query_string = scope.get("query_string", b"").decode("utf-8")
        auth_password = self._extract_auth_param(query_string)

        if auth_password:
            config = self.app.state.config
            if validate_password(auth_password, config.password):
                # Create session and redirect with cookie
                token = create_session(config.session_timeout)
                response = RedirectResponse(path, status_code=302)
                response.set_cookie(
                    SESSION_COOKIE_NAME,
                    token,
                    httponly=True,
                    samesite="lax",
                    path="/",
                )
                await response(scope, receive, send)
                return

            # A wrong ?auth= value from a requester with no valid session is a
            # failed login attempt; without this the QR parameter would be an
            # unthrottled brute-force oracle.
            await throttle_failed_login()

        # No valid session - redirect to login.
        # Preserve the original path for redirect after login. URL-encode
        # the `next` value so reserved characters (?, #, &) cannot smuggle
        # extra query params, and reject anything that doesn't look like a
        # same-origin path so we don't echo an open-redirect target back
        # into the login form.
        redirect_url = "/login"
        if path != "/" and path.startswith("/") and not path.startswith("//"):
            redirect_url = f"/login?next={quote(path, safe='/')}"

        response = RedirectResponse(redirect_url, status_code=302)
        await response(scope, receive, send)

    def _is_exempt_path(self, path: str) -> bool:
        """Check if a path is exempt from authentication.

        Args:
            path: The request path.

        Returns:
            bool: True if the path doesn't require authentication.
        """
        if path in self.EXEMPT_PATHS:
            return True

        return any(path.startswith(prefix) for prefix in self.EXEMPT_PREFIXES)

    def _get_session_cookie(self, scope: Scope) -> str | None:
        """Extract the session cookie value from ASGI scope headers.

        Scans for the specific cookie and returns immediately on match,
        avoiding parsing all cookies into a dict.

        Args:
            scope: The ASGI scope containing headers.

        Returns:
            str or None: The session cookie value, or None if not found.
        """
        for header_name, header_value in scope.get("headers", []):
            if header_name == b"cookie":
                # latin-1 decodes any byte sequence; session tokens are ASCII,
                # so a Cookie header with stray non-UTF-8 bytes (which h11
                # permits) degrades to a non-match instead of a 500.
                for item in header_value.decode("latin-1").split(";"):
                    item = item.strip()
                    if item.startswith(_SESSION_COOKIE_PREFIX):
                        return item[len(_SESSION_COOKIE_PREFIX) :]
        return None

    def _extract_auth_param(self, query_string: str) -> str | None:
        """Extract the auth parameter from a query string.

        Args:
            query_string: The URL query string.

        Returns:
            str or None: The auth parameter value, or None if not present.
        """
        if not query_string:
            return None

        for param in query_string.split("&"):
            if "=" in param:
                key, value = param.split("=", 1)
                if key == "auth":
                    # Percent-decode so passwords containing reserved or
                    # non-ASCII characters round-trip correctly.
                    return unquote(value)

        return None
