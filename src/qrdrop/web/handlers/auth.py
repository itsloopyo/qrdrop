"""Authentication handlers for login, logout, and session management."""

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from qrdrop.core.password import validate_password
from qrdrop.core.session import create_session, delete_session
from qrdrop.web.middleware import SESSION_COOKIE_NAME, throttle_failed_login


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


async def login_page_handler(request: Request) -> Response:
    """Render the login page.

    Args:
        request: The Starlette request object.

    Returns:
        Response: HTML response with the login form.
    """
    templates = request.app.state.templates

    next_path = _safe_next_path(request.query_params.get("next"))

    # Error messages are only ever rendered by the POST handler; reflecting an
    # ?error= query parameter would let a crafted link inject arbitrary text
    # into the trusted login card.
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": None,
            "next": next_path,
        },
    )


async def login_submit_handler(request: Request) -> Response:
    """Handle login form submission.

    Validates the password and creates a session on success.
    Uses timing-safe comparison to prevent timing attacks.

    Args:
        request: The Starlette request object.

    Returns:
        Response: Redirect to home on success, back to login with error on failure.
    """
    # Get form data
    form = await request.form()
    submitted_password = form.get("password", "")
    next_path = _safe_next_path(str(form.get("next", "/")))

    # Get expected password from config
    config = request.app.state.config
    expected_password = config.password

    # Validate using timing-safe comparison
    if validate_password(str(submitted_password), expected_password):
        # Success - create session
        token = create_session(config.session_timeout)

        # Redirect to requested path (already validated as safe).
        response = RedirectResponse(next_path, status_code=302)

        response.set_cookie(
            SESSION_COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            path="/",
        )

        return response

    # Failure - throttle, then re-render the login form with an error
    await throttle_failed_login()

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "login.html",
        {
            "error": "Invalid password",
            "next": next_path,
        },
        status_code=401,
    )


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
