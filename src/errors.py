"""Error envelope: every error response is {"error": ..., "status": ...}."""
from __future__ import annotations

import logging

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

log = logging.getLogger("13f-web")


async def http_exc_handler(_, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": exc.detail, "status": exc.status_code},
    )


async def validation_exc_handler(_, exc: RequestValidationError):
    return JSONResponse(
        status_code=422,
        content={"error": "Invalid request parameters", "detail": exc.errors(), "status": 422},
    )


async def db_missing_handler(_, exc: FileNotFoundError):
    # Log the path server-side; don't leak filesystem layout to clients
    log.error(f"Database unavailable: {exc}")
    return JSONResponse(
        status_code=503,
        content={"error": "Database unavailable", "status": 503},
    )


async def unhandled_exc_handler(request: Request, exc: Exception):
    log.exception(f"Unhandled error on {request.url.path}")
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error", "status": 500},
    )


def install_error_handlers(app: FastAPI) -> None:
    app.add_exception_handler(HTTPException, http_exc_handler)
    app.add_exception_handler(RequestValidationError, validation_exc_handler)
    app.add_exception_handler(FileNotFoundError, db_missing_handler)
    app.add_exception_handler(Exception, unhandled_exc_handler)
