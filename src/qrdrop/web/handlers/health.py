"""Health check endpoint for container orchestration."""

from starlette.requests import Request
from starlette.responses import JSONResponse


async def health_handler(_request: Request) -> JSONResponse:
    """Return health status for container health checks.

    Returns:
        JSONResponse: Health status with 200 OK.
    """
    return JSONResponse({"status": "healthy"})
