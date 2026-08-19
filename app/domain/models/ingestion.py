"""Versioned parser, chunk, job, and index-manifest contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from app.domain.models.common import ContractModel, Identifier
from app.domain.models.documents import MetadataValue
from app.domain.models.query import SourceLocation


class ElementType(StrEnum):
    """Normalized parser element types."""

    HEADING = "heading"
    PARAGRAPH = "paragraph"
    TABLE = "table"
    TABLE_ROW = "table_row"
    CODE = "code"
    LOG_RECORD = "log_record"


class DocumentElement(ContractModel):
    """Parser-independent source element used by chunking."""

    element_id: Identifier
    element_type: ElementType
    text: Annotated[str, Field(min_length=1, max_length=1_000_000)]
    ordinal: int = Field(ge=0)
    location: SourceLocation
    parser_confidence: float | None = Field(default=None, ge=0, le=1)


class ParsedDocument(ContractModel):
    """Normalized parser result."""

    document_id: Identifier
    document_version_id: Identifier
    tenant_id: Identifier
    checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    elements: list[DocumentElement]
    warning_codes: list[str] = Field(default_factory=list, max_length=1000)
    parser_version: Annotated[str, Field(min_length=1, max_length=128)]


class Chunk(ContractModel):
    """Deterministic indexable chunk with citation provenance."""

    chunk_id: Identifier
    document_id: Identifier
    document_version_id: Identifier
    tenant_id: Identifier
    checksum_sha256: Annotated[str, Field(pattern=r"^[a-f0-9]{64}$")]
    text: Annotated[str, Field(min_length=1, max_length=1_000_000)]
    ordinal: int = Field(ge=0)
    location: SourceLocation
    hierarchy_path: list[str] = Field(default_factory=list, max_length=32)
    token_count: int = Field(ge=1)
    parser_version: Annotated[str, Field(min_length=1, max_length=128)]
    chunker_version: Annotated[str, Field(min_length=1, max_length=128)]


class JobClaimState(StrEnum):
    """Durable filesystem job states."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class JobOperation(StrEnum):
    """Supported durable worker operations."""

    INGEST = "ingest"
    DELETE = "delete"


class IngestionJobState(ContractModel):
    """Recoverable ingestion job manifest."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    job_id: Identifier
    document_id: Identifier
    document_version_id: Identifier
    tenant_id: Identifier
    operation: JobOperation = JobOperation.INGEST
    claim_state: JobClaimState
    stage: Annotated[str, Field(min_length=1, max_length=64)]
    checksum_sha256: str | None = Field(default=None, pattern=r"^[a-f0-9]{64}$")
    filename: str | None = Field(default=None, min_length=1, max_length=255)
    content_type: str | None = Field(default=None, min_length=1, max_length=128)
    source_suffix: str | None = Field(default=None, pattern=r"^\.[a-z0-9]+$", max_length=16)
    user_metadata: dict[str, MetadataValue] = Field(default_factory=dict, max_length=64)
    parser_version: Annotated[str, Field(min_length=1, max_length=128)]
    chunker_version: Annotated[str, Field(min_length=1, max_length=128)]
    index_schema_version: Annotated[str, Field(min_length=1, max_length=64)]
    retry_count: int = Field(default=0, ge=0, le=100)
    failure_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]+$", max_length=64)
    created_at: datetime
    updated_at: datetime

    @model_validator(mode="after")
    def validate_ingestion_fields(self) -> IngestionJobState:
        if self.operation is JobOperation.INGEST:
            required = {
                "checksum_sha256": self.checksum_sha256,
                "filename": self.filename,
                "content_type": self.content_type,
                "source_suffix": self.source_suffix,
            }
            missing = sorted(name for name, value in required.items() if value is None)
            if missing:
                raise ValueError(f"ingestion job is missing fields: {missing}")
        return self


class IndexManifest(ContractModel):
    """Version manifest for an indexed document."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    document_version_id: Identifier
    collection_alias_target: Annotated[str, Field(min_length=1, max_length=255)]
    index_schema_version: Annotated[str, Field(min_length=1, max_length=64)]
    chunk_count: int = Field(ge=0)
    parser_version: Annotated[str, Field(min_length=1, max_length=128)]
    chunker_version: Annotated[str, Field(min_length=1, max_length=128)]
    dense_model_revision: Annotated[str, Field(min_length=1, max_length=256)]
    sparse_model_revision: Annotated[str, Field(min_length=1, max_length=256)]
