"""Directory browsing handler.

Handles directory listing requests with breadcrumb navigation,
sorting (directories first), and human-readable file sizes.
"""

from dataclasses import dataclass
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from qrdrop.core.filesystem import FileEntry, list_directory, sort_entries
from qrdrop.core.filetypes import get_file_icon
from qrdrop.web.handlers._common import resolve_existing_target


@dataclass
class BreadcrumbItem:
    """Represents a breadcrumb navigation item."""

    name: str
    path: str


def build_breadcrumbs(path: str) -> list[BreadcrumbItem]:
    """Build breadcrumb navigation items from a path.

    Args:
        path: The current path (relative to root).

    Returns:
        list[BreadcrumbItem]: List of breadcrumb items starting from root.
    """
    breadcrumbs = [BreadcrumbItem(name="Home", path="")]

    if not path or path == "/" or path == ".":
        return breadcrumbs

    # Split path into components
    parts = path.strip("/").split("/")
    accumulated_path = ""

    for part in parts:
        if part:  # Skip empty parts
            accumulated_path = f"{accumulated_path}/{part}" if accumulated_path else part
            breadcrumbs.append(BreadcrumbItem(name=part, path=accumulated_path))

    return breadcrumbs


def _get_sort_params(request: Request) -> tuple[str, str]:
    """Extract and validate sort parameters from request query string.

    Args:
        request: The Starlette request object.

    Returns:
        tuple[str, str]: (sort_by, sort_order) with validated values.
    """
    sort_by = request.query_params.get("sort", "name")
    sort_order = request.query_params.get("order", "asc")

    if sort_by not in ("name", "size", "modified"):
        sort_by = "name"
    if sort_order not in ("asc", "desc"):
        sort_order = "asc"

    return sort_by, sort_order


def _entry_row(entry: FileEntry, current_path: str) -> dict[str, Any]:
    """Template data for one listing row."""
    return {
        "name": entry.name,
        "path": f"{current_path}/{entry.name}" if current_path else entry.name,
        "size_human": entry.size_human,
        "size_bytes": entry.size_bytes,
        "mtime": entry.mtime.strftime("%Y-%m-%d %H:%M"),
        "is_dir": entry.is_dir,
        "is_hidden": entry.is_hidden,
        "icon": get_file_icon(entry),
    }


async def browse_handler(request: Request) -> Response:
    """Handle directory browsing requests.

    Lists directory contents with file information and breadcrumb navigation.

    Args:
        request: The Starlette request object.

    Returns:
        Response: HTML response with directory listing.
    """
    path = request.path_params.get("path", "")
    config = request.app.state.config

    target = resolve_existing_target(request)
    if isinstance(target, Response):
        return target

    if not target.is_dir():
        return RedirectResponse(f"/view/{quote(path)}", status_code=302)

    try:
        entries = list_directory(target, show_hidden=config.show_hidden)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        # The exception message embeds the absolute server-side path.
        return Response("Not found", status_code=404)

    sort_by, sort_order = _get_sort_params(request)
    entries = sort_entries(entries, sort_by=sort_by, sort_order=sort_order)

    current_path = path.strip("/")

    # Title is the basename of the directory we're in; the template falls back
    # to the served root's name (site_name) at the top level.
    page_title = current_path.rsplit("/", 1)[-1] if current_path else ""

    dir_count = sum(1 for entry in entries if entry.is_dir)

    templates = request.app.state.templates
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "entries": [_entry_row(entry, current_path) for entry in entries],
            "breadcrumbs": build_breadcrumbs(path),
            "current_path": current_path,
            "page_title": page_title,
            "total_items": len(entries),
            "dir_count": dir_count,
            "file_count": len(entries) - dir_count,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "allow_upload": config.allow_upload,
            "allow_delete": config.allow_delete,
            "allow_modify": config.allow_modify,
        },
    )
