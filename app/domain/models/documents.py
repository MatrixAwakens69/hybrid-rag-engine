"""Version-one document lifecycle contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.domain.models.common import ContractModel, Identifier, VersionManifest

MetadataValue = str | int | float | bool


class DocumentStatus(StrEnum):
    """Externally visible ingestion and deletion states."""

    ACCEPTED = "accepted"
    PARSING = "parsing"
    CHUNKING = "chunking"
    INDEXING = "indexing"
    READY = "ready"
    FAILED = "failed"
    DELETING = "deleting"
    DELETED = "deleted"


class DocumentWarning(ContractModel):
    """Safe, non-terminal processing warning."""

    code: Annotated[str, Field(pattern=r"^[a-z0-9_]+$", min_length=3, max_length=64)]
    message: Annotated[str, Field(min_length=1, max_length=512)]


class DocumentMetadata(ContractModel):
    """Tenant-safe document metadata."""

    document_id: Identifier
    filename: Annotated[str, Field(min_length=1, max_length=255)]
    content_type: Annotated[str, Field(min_length=1, max_length=128)]
    checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    status: DocumentStatus
    user_metadata: dict[str, MetadataValue] = Field(default_factory=dict, max_length=64)
    created_at: datetime
    updated_at: datetime


class DocumentUploadResponse(ContractModel):
    """Acknowledgement returned after a durable ingestion job is accepted."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    document_id: Identifier
    status: DocumentStatus = DocumentStatus.ACCEPTED
    request_id: Identifier


class DocumentStatusResponse(ContractModel):
    """Current processing state without unsafe parser or provider details."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    document: DocumentMetadata
    warnings: list[DocumentWarning] = Field(default_factory=list, max_length=100)
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=64)
    versions: VersionManifest


class DocumentRecord(ContractModel):
    """Internal tenant-scoped document control record."""

    tenant_id: Identifier
    document: DocumentMetadata
    warnings: list[DocumentWarning] = Field(default_factory=list, max_length=100)
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=64)
    versions: VersionManifest


class DocumentListResponse(ContractModel):
    """Cursor-paginated document listing."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    items: list[DocumentMetadata] = Field(max_length=100)
    next_cursor: str | None = Field(default=None, max_length=512)
    has_more: bool


class DocumentDeletionResponse(ContractModel):
    """Idempotent deletion status and honest backup-retention boundary."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    document_id: Identifier
    status: DocumentStatus
    retention_notice: Annotated[str, Field(min_length=1, max_length=512)]
    request_id: Identifier
