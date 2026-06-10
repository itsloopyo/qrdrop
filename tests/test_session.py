"""Tests for in-memory session management."""

import time

import pytest

from qrdrop.core import session as session_mod
from qrdrop.core.session import (
    cleanup_expired_sessions,
    create_session,
    delete_session,
    validate_session,
)


@pytest.fixture(autouse=True)
def _reset_sessions() -> None:
    session_mod._sessions.clear()
    session_mod._last_cleanup_time = 0.0
    yield
    session_mod._sessions.clear()


class TestCreateSession:
    def test_returns_token_string(self) -> None:
        token = create_session(60)
        assert isinstance(token, str)
        assert len(token) > 20

    def test_unique_tokens(self) -> None:
        tokens = {create_session(60) for _ in range(50)}
        assert len(tokens) == 50

    def test_session_stored(self) -> None:
        token = create_session(60)
        assert len(session_mod._sessions) == 1
        assert token in session_mod._sessions

    def test_expiry_in_future(self) -> None:
        token = create_session(60)
        assert session_mod._sessions[token].expires_at > time.time()

    def test_default_never_expires(self) -> None:
        token = create_session()
        assert session_mod._sessions[token].expires_at == float("inf")
        assert validate_session(token) is True


class TestValidateSession:
    def test_unknown_token_returns_false(self) -> None:
        assert validate_session("nope") is False

    def test_valid_token_returns_true(self) -> None:
        token = create_session(60)
        assert validate_session(token) is True

    def test_expired_token_returns_false_and_removes(self) -> None:
        token = create_session(timeout_seconds=-1)
        assert validate_session(token) is False
        assert token not in session_mod._sessions

    def test_empty_string_token(self) -> None:
        assert validate_session("") is False


class TestDeleteSession:
    def test_removes_existing_session(self) -> None:
        token = create_session(60)
        delete_session(token)
        assert len(session_mod._sessions) == 0

    def test_unknown_token_no_error(self) -> None:
        delete_session("does-not-exist")  # must not raise


class TestCleanup:
    def test_cleanup_removes_only_expired(self) -> None:
        live = create_session(60)
        forever = create_session()
        dead = create_session(-1)
        removed = cleanup_expired_sessions()
        assert removed == 1
        assert live in session_mod._sessions
        assert forever in session_mod._sessions
        assert dead not in session_mod._sessions

    def test_cleanup_returns_zero_when_none_expired(self) -> None:
        create_session(60)
        assert cleanup_expired_sessions() == 0
