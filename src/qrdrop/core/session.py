"""Session management for authentication.

Sessions are stored in memory (module-level dict) and are lost on restart.
This is intentional for a temporary file-sharing tool.
"""

import secrets
import time
from dataclasses import dataclass


@dataclass(slots=True)
class SessionData:
    """Represents an authenticated session.

    Stores timestamps as epoch floats for fast comparison. Sessions that
    never expire use float("inf") so validation and cleanup need no
    special-casing.
    """

    token: str
    created_at: float
    expires_at: float


_sessions: dict[str, SessionData] = {}

# Sweep expired sessions at most this often, regardless of traffic.
_CLEANUP_INTERVAL_SECONDS = 60.0
_last_cleanup_time: float = 0.0


def create_session(timeout_seconds: int | None = None) -> str:
    """Create a new authenticated session.

    Generates a cryptographically secure token and stores the session.

    Args:
        timeout_seconds: How long the session should remain valid, or None
            to keep it valid for the life of the process (default).

    Returns:
        str: A URL-safe base64-encoded token (32 bytes of entropy).
    """
    token = secrets.token_urlsafe(32)
    now = time.time()
    _sessions[token] = SessionData(
        token=token,
        created_at=now,
        expires_at=now + timeout_seconds if timeout_seconds is not None else float("inf"),
    )
    return token


def _maybe_cleanup(now: float) -> None:
    """Sweep expired sessions, but at most once per `_CLEANUP_INTERVAL_SECONDS`.

    Called on every validate_session; the rate limit makes the amortized cost
    O(active sessions / interval) regardless of validation volume.
    """
    global _last_cleanup_time
    if now - _last_cleanup_time < _CLEANUP_INTERVAL_SECONDS:
        return
    _last_cleanup_time = now
    cleanup_expired_sessions()


def validate_session(token: str) -> bool:
    """Check if a session token is valid and not expired.

    Args:
        token: The session token to validate.

    Returns:
        bool: True if the session is valid and not expired, False otherwise.
    """
    session = _sessions.get(token)
    if session is None:
        return False

    now = time.time()
    if now > session.expires_at:
        # pop() tolerates concurrent validations racing on the same token.
        _sessions.pop(token, None)
        return False

    _maybe_cleanup(now)
    return True


def delete_session(token: str) -> None:
    """Delete a session (logout).

    Args:
        token: The session token to delete.
    """
    _sessions.pop(token, None)


def cleanup_expired_sessions() -> int:
    """Remove all expired sessions from storage.

    Returns:
        int: The number of sessions that were removed.
    """
    now = time.time()
    expired_tokens = [token for token, session in _sessions.items() if now > session.expires_at]
    for token in expired_tokens:
        del _sessions[token]
    return len(expired_tokens)
