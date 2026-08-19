"""Shared version-one domain contracts."""

from __future__ import annotations

from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")]
SafeMessage = Annotated[str, Field(min_length=1, max_length=1024)]


class ContractModel(BaseModel):
    """Strict base for public and persisted version-one contracts."""

    model_config = ConfigDict(extra="forbid")


class TenantPrincipal(ContractModel):
    """Authoritative identity produced by authentication, never request input."""

    tenant_id: Identifier
    key_id: Identifier
    scopes: frozenset[str] = frozenset()


class APIKeyRecord(ContractModel):
    """Persisted hash-only API-key record."""

    key_id: Identifier
    tenant_id: Identifier
    secret_hash: Annotated[str, Field(min_length=32, max_length=1024)]
    scopes: frozenset[str] = frozenset()
    enabled: bool = True
    created_at: datetime
    expires_at: datetime | None = None


class FieldViolation(ContractModel):
    """Bounded validation detail safe to return to a caller."""

    field: Annotated[str, Field(min_length=1, max_length=128)]
    message: SafeMessage


class ErrorDetail(ContractModel):
    """Stable public error body."""

    code: Annotated[str, Field(pattern=r"^[a-z0-9_]+$", min_length=3, max_length=64)]
    message: SafeMessage
    request_id: Identifier
    retryable: bool = False
    field_violations: list[FieldViolation] = Field(default_factory=list, max_length=32)


class ErrorResponse(ContractModel):
    """Versioned error envelope."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    error: ErrorDetail


class VersionManifest(ContractModel):
    """Versions needed to reproduce a query or ingestion result."""

    app_revision: Annotated[str, Field(min_length=1, max_length=128)]
    index_schema_version: Annotated[str, Field(min_length=1, max_length=64)]
    parser_version: str | None = Field(default=None, max_length=128)
    chunker_version: str | None = Field(default=None, max_length=128)
    dense_model_revision: str | None = Field(default=None, max_length=256)
    sparse_model_revision: str | None = Field(default=None, max_length=256)
    reranker_model_revision: str | None = Field(default=None, max_length=256)
    generator_model_revision: str | None = Field(default=None, max_length=256)
    prompt_version: str | None = Field(default=None, max_length=128)


class TimestampedModel(ContractModel):
    """Common UTC lifecycle timestamps."""

    created_at: datetime
    updated_at: datetime
