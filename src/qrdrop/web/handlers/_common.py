"""Shared request helpers for file/directory handlers."""

import os
from pathlib import Path
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, Response

from qrdrop.core.filesystem import (
    PathTraversalError,
    SymlinkEscapeError,
    validate_path,
)


class RequestValidationError(Exception):
    """Raised when a mutating request fails validation.

    Carries an HTTP status code and a user-facing message so callers can
    translate it into a JSON error response without re-deriving either.
    """

    def __init__(self, message: str, status_code: int) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def validate_target_directory(root: Path, target_dir_path: str) -> Path:
    """Validate that `target_dir_path` resolves to a writable directory under root.

    Raises:
        RequestValidationError: If the path escapes root, is not a directory,
            or is not writable. Carries the appropriate HTTP status.
    """
    try:
        target_dir = validate_path(root, target_dir_path)
    except (PathTraversalError, SymlinkEscapeError) as e:
        raise RequestValidationError("Invalid path", 403) from e

    if not target_dir.is_dir():
        raise RequestValidationError("Target path is not a directory", 400)

    if not os.access(target_dir, os.W_OK):
        raise RequestValidationError("Directory is not writable", 403)

    return target_dir


def sanitize_name(name: str | None) -> str:
    """Reduce `name` to a safe basename for a file or directory.

    Raises:
        RequestValidationError: If the name is missing, empty, or resolves to a
            path component that cannot be used as a real entry name.
    """
    if not name:
        raise RequestValidationError("No name provided", 400)

    # Only take the basename to prevent path injection
    safe_name = Path(name).name

    if not safe_name or safe_name in (".", ".."):
        raise RequestValidationError("Invalid name", 400)

    # On NTFS a ":" in a name addresses an alternate data stream ("file:hidden"
    # writes a hidden stream on "file"), so it can't be part of a real entry name.
    if os.name == "nt" and ":" in safe_name:
        raise RequestValidationError("Invalid name", 400)

    return safe_name


def validation_error_response(
    error: RequestValidationError, *, with_results: bool = False
) -> JSONResponse:
    """Build a JSON error response from a RequestValidationError."""
    payload: dict[str, Any] = {"error": error.message, "success": False}
    if with_results:
        payload["results"] = []
    return JSONResponse(payload, status_code=error.status_code)


def resolve_existing_target(request: Request) -> Path | Response:
    """Resolve the request's ``path`` param to an existing path under the root.

    Centralizes the security boundary shared by the browse, view, and download
    handlers: a path that escapes the root yields a 403 and a missing target
    yields a 404. Returns the resolved :class:`~pathlib.Path` on success, or the
    error :class:`~starlette.responses.Response` the caller should return as-is.
    """
    path = request.path_params.get("path", "")
    root = request.app.state.config.root_dir

    try:
        target = validate_path(root, path)
    except (PathTraversalError, SymlinkEscapeError):
        return Response("Access denied", status_code=403)

    if not target.exists():
        return Response("Not found", status_code=404)

    return target
