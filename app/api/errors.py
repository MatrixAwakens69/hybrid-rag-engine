"""Centralized mapping from internal failures to stable public errors."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.domain.errors import DependencyUnavailableError, ServiceError
from app.domain.models.common import ErrorDetail, ErrorResponse, FieldViolation

logger = structlog.get_logger(__name__)


def _request_id(request: Request) -> str:
    value: Any = getattr(request.state, "request_id", None)
    return value if isinstance(value, str) else uuid4().hex


def _response(detail: ErrorDetail, status_code: int) -> JSONResponse:
    body = ErrorResponse(error=detail)
    return JSONResponse(status_code=status_code, content=body.model_dump(mode="json"))


def register_exception_handlers(app: FastAPI) -> None:
    """Install safe handlers in one composition location."""

    @app.exception_handler(RequestValidationError)
    async def validation_handler(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        violations = [
            FieldViolation(
                field=".".join(str(part) for part in error["loc"]),
                message=str(error["msg"])[:1024],
            )
            for error in exc.errors()[:32]
        ]
        return _response(
            ErrorDetail(
                code="request_validation_failed",
                message="The request did not satisfy the API contract.",
                request_id=_request_id(request),
                field_violations=violations,
            ),
            422,
        )

    @app.exception_handler(ServiceError)
    async def service_error_handler(request: Request, exc: ServiceError) -> JSONResponse:
        status_code = 503 if isinstance(exc, DependencyUnavailableError) else 400
        return _response(
            ErrorDetail(
                code=exc.code,
                message=exc.public_message,
                request_id=_request_id(request),
                retryable=exc.retryable,
            ),
            status_code,
        )

    @app.exception_handler(Exception)
    async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("unhandled_request_error", error_type=type(exc).__name__)
        return _response(
            ErrorDetail(
                code="internal_error",
                message="The service encountered an unexpected error.",
                request_id=_request_id(request),
                retryable=False,
            ),
            500,
        )
