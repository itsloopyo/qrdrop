"""Directory browsing handler.

Handles directory listing requests with breadcrumb navigation,
sorting (directories first), and human-readable file sizes.
"""

from dataclasses import dataclass
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from qrdrop.core.filesystem import (
    list_directory,
    sort_entries,
)
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


async def browse_handler(request: Request) -> Response:
    """Handle directory browsing requests.

    Lists directory contents with file information and breadcrumb navigation.

    Args:
        request: The Starlette request object.

    Returns:
        Response: HTML response with directory listing.
    """
    # Get path from URL parameter (empty string for root)
    path = request.path_params.get("path", "")
    show_hidden = request.app.state.config.show_hidden

    target = resolve_existing_target(request)
    if isinstance(target, Response):
        return target

    if not target.is_dir():
        return RedirectResponse(f"/view/{quote(path)}", status_code=302)

    # List directory contents
    try:
        entries = list_directory(target, show_hidden=show_hidden)
    except (FileNotFoundError, NotADirectoryError, PermissionError):
        # The exception message embeds the absolute server-side path.
        return Response("Not found", status_code=404)

    # Get sort parameters from query string
    sort_by, sort_order = _get_sort_params(request)

    # Sort entries
    entries = sort_entries(entries, sort_by=sort_by, sort_order=sort_order)

    # Build breadcrumbs
    breadcrumbs = build_breadcrumbs(path)

    # Calculate relative paths for links
    current_path = path.strip("/") if path else ""

    # Title is the basename of the directory we're in; the template falls back
    # to the served root's name (site_name) at the top level.
    page_title = current_path.rsplit("/", 1)[-1] if current_path else ""

    # Build entry data with paths and icons, counting dirs/files in one pass
    entry_data = []
    dir_count = 0
    file_count = 0
    for entry in entries:
        entry_path = f"{current_path}/{entry.name}" if current_path else entry.name

        if entry.is_dir:
            dir_count += 1
        else:
            file_count += 1

        entry_data.append(
            {
                "name": entry.name,
                "path": entry_path,
                "size_human": entry.size_human,
                "size_bytes": entry.size_bytes,
                "mtime": entry.mtime.strftime("%Y-%m-%d %H:%M"),
                "is_dir": entry.is_dir,
                "is_hidden": entry.is_hidden,
                "icon": get_file_icon(entry),
            }
        )

    # Render template
    templates = request.app.state.templates
    config = request.app.state.config
    return templates.TemplateResponse(
        request,
        "browse.html",
        {
            "entries": entry_data,
            "breadcrumbs": breadcrumbs,
            "current_path": current_path,
            "page_title": page_title,
            "total_items": len(entries),
            "dir_count": dir_count,
            "file_count": file_count,
            "sort_by": sort_by,
            "sort_order": sort_order,
            "allow_upload": config.allow_upload,
            "allow_delete": config.allow_delete,
            "allow_modify": config.allow_modify,
        },
    )
