"""Shared request helpers for file/directory handlers."""

import json
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote

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


def json_error(message: str, status_code: int, **extra: Any) -> JSONResponse:
    """Build the ``{"success": false, "error": ...}`` body every JSON endpoint uses."""
    return JSONResponse({"success": False, "error": message, **extra}, status_code=status_code)


def validation_error_response(
    error: RequestValidationError, *, with_results: bool = False
) -> JSONResponse:
    """Build a JSON error response from a RequestValidationError."""
    if with_results:
        return json_error(error.message, error.status_code, results=[])
    return json_error(error.message, error.status_code)


async def read_json_object(request: Request) -> dict:
    """Parse the request body as a JSON object.

    Raises:
        RequestValidationError: If the body is not valid JSON or not an object.
    """
    try:
        body = await request.json()
    except json.JSONDecodeError as e:
        raise RequestValidationError("Invalid JSON body", 400) from e

    if not isinstance(body, dict):
        raise RequestValidationError("Request body must be a JSON object", 400)
    return body


def _require_str_path(path: object) -> None:
    """Reject a non-string path from a JSON body before it reaches validate_path."""
    if not isinstance(path, str):
        raise RequestValidationError("Path must be a string", 400)


def resolve_existing_path(root: Path, path: str) -> Path:
    """Resolve `path` to an existing entry under root.

    Raises:
        RequestValidationError: 400 if the path is not a string, 403 if it
            escapes root, 404 if nothing exists there.
    """
    _require_str_path(path)
    try:
        target = validate_path(root, path)
    except (PathTraversalError, SymlinkEscapeError) as e:
        raise RequestValidationError("Access denied", 403) from e

    if not target.exists():
        raise RequestValidationError("Not found", 404)

    return target


def named_entry(root: Path, path: str, resolved: Path) -> Path:
    """The entry the client named at `path`: the link itself if it is a symlink.

    `resolved` (from :func:`resolve_existing_path`) is what the link points
    at; deleting or renaming that instead would act on the link's target.
    """
    link = root / path.lstrip("/")
    return link if link.is_symlink() else resolved


def resolve_existing_target(request: Request) -> Path | Response:
    """Resolve the request's ``path`` param to an existing path under the root.

    The plain-text counterpart of :func:`resolve_existing_path` for the
    browse, view, and download handlers. Returns the resolved
    :class:`~pathlib.Path` on success, or the error
    :class:`~starlette.responses.Response` the caller should return as-is.
    """
    try:
        return resolve_existing_path(
            request.app.state.config.root_dir, request.path_params.get("path", "")
        )
    except RequestValidationError as e:
        return Response(e.message, status_code=e.status_code)


def validate_target_directory(root: Path, target_dir_path: str) -> Path:
    """Validate that `target_dir_path` resolves to a writable directory under root.

    Raises:
        RequestValidationError: If the path is not a string, escapes root, is
            not a directory, or is not writable. Carries the appropriate HTTP
            status.
    """
    _require_str_path(target_dir_path)
    try:
        target_dir = validate_path(root, target_dir_path)
    except (PathTraversalError, SymlinkEscapeError) as e:
        raise RequestValidationError("Invalid path", 403) from e

    if not target_dir.is_dir():
        raise RequestValidationError("Target path is not a directory", 400)

    if not os.access(target_dir, os.W_OK):
        raise RequestValidationError("Directory is not writable", 403)

    return target_dir


def sanitize_name(name: object) -> str:
    """Reduce `name` to a safe basename for a file or directory.

    Raises:
        RequestValidationError: If the name is missing, empty, or resolves to a
            path component that cannot be used as a real entry name.
    """
    if not name:
        raise RequestValidationError("No name provided", 400)
    if not isinstance(name, str):
        raise RequestValidationError("Invalid name", 400)

    # Only take the basename to prevent path injection
    safe_name = Path(name).name

    if not safe_name or safe_name in (".", ".."):
        raise RequestValidationError("Invalid name", 400)

    # On NTFS a ":" in a name addresses an alternate data stream ("file:hidden"
    # writes a hidden stream on "file"), so it can't be part of a real entry name.
    if os.name == "nt" and ":" in safe_name:
        raise RequestValidationError("Invalid name", 400)

    return safe_name


def os_error_reason(error: OSError) -> str:
    """The path-free reason for an OS-level failure.

    str(error) embeds the absolute server-side path, which must not reach the
    client; strerror carries only the reason.
    """
    return error.strerror or str(error)


def content_disposition(filename: str, disposition: str) -> str:
    """Build a header-injection-safe Content-Disposition value (RFC 6266).

    Filenames on POSIX may legally contain characters that are unsafe in a
    quoted HTTP header value (CR, LF, double-quote, backslash). Strip them
    from the ASCII fallback and additionally provide a UTF-8 percent-encoded
    `filename*` parameter so unicode names survive intact.
    """
    # ASCII-safe fallback: drop control chars, backslashes, and quotes; use
    # a placeholder if nothing useful remains.
    ascii_safe = "".join(c for c in filename if 32 <= ord(c) < 127 and c not in '"\\').strip()
    if not ascii_safe:
        ascii_safe = "download"
    encoded = quote(filename, safe="")
    return f"{disposition}; filename=\"{ascii_safe}\"; filename*=UTF-8''{encoded}"
