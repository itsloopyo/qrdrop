"""Authentication handlers for login, logout, and session management."""

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from qrdrop.core.password import validate_password
from qrdrop.core.session import create_session, delete_session
from qrdrop.web.middleware import (
    SESSION_COOKIE_NAME,
    set_session_cookie,
    throttle_failed_login,
)


def _safe_next_path(candidate: str | None) -> str:
    """Return a same-origin relative path or "/" if the candidate is unsafe.

    Prevents open-redirect attacks where an attacker crafts a login URL with
    `next=//evil.example` or `next=https://evil.example` and tricks an
    authenticated user into bouncing offsite after login.
    """
    if not candidate:
        return "/"
    # Must be a path on this origin: starts with a single "/" and is not a
    # protocol-relative or backslash-prefixed URL, and must not contain
    # CR/LF (header injection) or a scheme separator.
    if (
        not candidate.startswith("/")
        or candidate.startswith("//")
        or candidate.startswith("/\\")
        or "\r" in candidate
        or "\n" in candidate
    ):
        return "/"
    return candidate


def _render_login(
    request: Request, next_path: str, error: str | None = None, status_code: int = 200
) -> Response:
    return request.app.state.templates.TemplateResponse(
        request,
        "login.html",
        {"error": error, "next": next_path},
        status_code=status_code,
    )


async def login_page_handler(request: Request) -> Response:
    """Render the login page.

    Args:
        request: The Starlette request object.

    Returns:
        Response: HTML response with the login form.
    """
    # Error messages are only ever rendered by the POST handler; reflecting an
    # ?error= query parameter would let a crafted link inject arbitrary text
    # into the trusted login card.
    return _render_login(request, _safe_next_path(request.query_params.get("next")))


async def login_submit_handler(request: Request) -> Response:
    """Handle login form submission.

    Validates the password and creates a session on success.
    Uses timing-safe comparison to prevent timing attacks.

    Args:
        request: The Starlette request object.

    Returns:
        Response: Redirect to home on success, back to login with error on failure.
    """
    form = await request.form()
    submitted_password = form.get("password", "")
    next_path = _safe_next_path(str(form.get("next", "/")))
    config = request.app.state.config

    if validate_password(str(submitted_password), config.password):
        response = RedirectResponse(next_path, status_code=302)
        set_session_cookie(response, create_session(config.session_timeout))
        return response

    await throttle_failed_login()
    return _render_login(request, next_path, error="Invalid password", status_code=401)


async def logout_handler(request: Request) -> Response:
    """Handle logout by deleting the session.

    Args:
        request: The Starlette request object.

    Returns:
        Response: Redirect to login page with session cookie cleared.
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if session_token:
        delete_session(session_token)

    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie(SESSION_COOKIE_NAME, path="/")
    return response
