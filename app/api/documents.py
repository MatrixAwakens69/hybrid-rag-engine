"""Authenticated version-one document lifecycle endpoints."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Annotated, Any, cast

from fastapi import APIRouter, File, Form, Query, Request, UploadFile, status
from pydantic import TypeAdapter, ValidationError

from app.api.dependencies import PrincipalDependency, ServicesDependency
from app.config import Settings
from app.domain.errors import InvalidUploadError, RequestTimeoutError
from app.domain.models import (
    DocumentDeletionResponse,
    DocumentListResponse,
    DocumentStatusResponse,
    DocumentUploadResponse,
    ErrorResponse,
)
from app.domain.models.documents import MetadataValue

router = APIRouter(prefix="/v1/documents", tags=["documents"])
_metadata_adapter = TypeAdapter(dict[str, MetadataValue])
_error_responses: dict[int | str, dict[str, Any]] = {
    401: {"model": ErrorResponse},
    403: {"model": ErrorResponse},
    404: {"model": ErrorResponse},
    413: {"model": ErrorResponse},
    415: {"model": ErrorResponse},
    422: {"model": ErrorResponse},
    503: {"model": ErrorResponse},
}


def _request_id(request: Request) -> str:
    return cast(str, request.state.request_id)


@router.post(
    "",
    response_model=DocumentUploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses,
)
async def upload_document(
    request: Request,
    principal: PrincipalDependency,
    services: ServicesDependency,
    file: Annotated[UploadFile, File(description="PDF, CSV, Markdown, text, or log file")],
    metadata_json: Annotated[str, Form()] = "{}",
    force_reindex: Annotated[bool, Form()] = False,
) -> DocumentUploadResponse:
    try:
        raw_metadata = json.loads(metadata_json)
        metadata = _metadata_adapter.validate_python(raw_metadata)
    except (json.JSONDecodeError, ValidationError) as exc:
        raise InvalidUploadError(public_message="Document metadata is invalid.") from exc
    settings = cast(Settings, request.app.state.settings)

    async def chunks() -> AsyncIterator[bytes]:
        while chunk := await file.read(1024 * 1024):
            yield chunk

    try:
        async with asyncio.timeout(settings.request_timeout_seconds):
            record = await services.documents.upload(
                principal,
                filename=file.filename or "document",
                content_type=file.content_type or "application/octet-stream",
                metadata=metadata,
                chunks=chunks(),
                force_reindex=force_reindex,
            )
    except TimeoutError as exc:
        raise RequestTimeoutError() from exc
    finally:
        await file.close()
    return DocumentUploadResponse(
        document_id=record.document.document_id,
        status=record.document.status,
        request_id=_request_id(request),
    )


@router.get(
    "/{document_id}",
    response_model=DocumentStatusResponse,
    responses=_error_responses,
)
async def get_document(
    document_id: str,
    principal: PrincipalDependency,
    services: ServicesDependency,
) -> DocumentStatusResponse:
    record = await services.documents.get(principal, document_id)
    return DocumentStatusResponse(
        document=record.document,
        warnings=record.warnings,
        failure_code=record.failure_code,
        versions=record.versions,
    )


@router.get(
    "",
    response_model=DocumentListResponse,
    responses=_error_responses,
)
async def list_documents(
    principal: PrincipalDependency,
    services: ServicesDependency,
    cursor: Annotated[str | None, Query(max_length=512)] = None,
    limit: Annotated[int, Query(ge=1, le=100)] = 50,
) -> DocumentListResponse:
    records, next_cursor = await services.documents.list(
        principal,
        cursor=cursor,
        limit=limit,
    )
    return DocumentListResponse(
        items=[record.document for record in records],
        next_cursor=next_cursor,
        has_more=next_cursor is not None,
    )


@router.delete(
    "/{document_id}",
    response_model=DocumentDeletionResponse,
    status_code=status.HTTP_202_ACCEPTED,
    responses=_error_responses,
)
async def delete_document(
    request: Request,
    document_id: str,
    principal: PrincipalDependency,
    services: ServicesDependency,
) -> DocumentDeletionResponse:
    record = await services.documents.delete(principal, document_id)
    return DocumentDeletionResponse(
        document_id=record.document.document_id,
        status=record.document.status,
        retention_notice=(
            "Active source and derived data are removed asynchronously; "
            "expired backups are removed by the configured retention policy."
        ),
        request_id=_request_id(request),
    )
