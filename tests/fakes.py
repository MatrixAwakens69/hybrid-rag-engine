"""Deterministic in-memory adapters shared by Phase 1 tests."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime

from app.domain.errors import UnauthorizedError
from app.domain.models import (
    DocumentRecord,
    DocumentStatus,
    DocumentWarning,
    IngestionJobState,
    TenantPrincipal,
    VersionManifest,
)
from app.domain.policies.lifecycle import require_transition


class MemoryAuthenticator:
    def __init__(self) -> None:
        scopes = frozenset(
            {
                "documents:read",
                "documents:write",
                "documents:delete",
                "ingestion:force_reindex",
            }
        )
        self.principals = {
            "tenant-a-key": TenantPrincipal(
                tenant_id="tenant-a",
                key_id="key-a",
                scopes=scopes,
            ),
            "tenant-b-key": TenantPrincipal(
                tenant_id="tenant-b",
                key_id="key-b",
                scopes=scopes,
            ),
        }

    async def authenticate(self, token: str) -> TenantPrincipal:
        principal = self.principals.get(token)
        if principal is None:
            raise UnauthorizedError()
        return principal


class MemoryDocumentRepository:
    def __init__(self) -> None:
        self.records: dict[str, DocumentRecord] = {}

    async def get(
        self,
        principal: TenantPrincipal,
        document_id: str,
    ) -> DocumentRecord | None:
        record = self.records.get(document_id)
        if record is None or record.tenant_id != principal.tenant_id:
            return None
        return record

    async def list(
        self,
        principal: TenantPrincipal,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[DocumentRecord], str | None]:
        records = sorted(
            (record for record in self.records.values() if record.tenant_id == principal.tenant_id),
            key=lambda record: record.document.document_id,
        )
        offset = int(cursor or "0")
        page = records[offset : offset + limit]
        next_offset = offset + len(page)
        next_cursor = str(next_offset) if next_offset < len(records) else None
        return page, next_cursor

    async def upsert(
        self,
        principal: TenantPrincipal,
        document: DocumentRecord,
    ) -> None:
        if principal.tenant_id != document.tenant_id:
            raise ValueError("tenant mismatch")
        self.records[document.document.document_id] = document

    async def set_status(
        self,
        principal: TenantPrincipal,
        document_id: str,
        status: DocumentStatus,
        *,
        failure_code: str | None = None,
        warnings: Sequence[DocumentWarning] | None = None,
        versions: VersionManifest | None = None,
    ) -> None:
        record = await self.get(principal, document_id)
        if record is None:
            return
        require_transition(record.document.status, status)
        metadata = record.document.model_copy(
            update={"status": status, "updated_at": datetime.now(UTC)}
        )
        self.records[document_id] = record.model_copy(
            update={
                "document": metadata,
                "failure_code": failure_code,
                "warnings": list(warnings) if warnings is not None else record.warnings,
                "versions": versions or record.versions,
            }
        )

    async def delete(self, principal: TenantPrincipal, document_id: str) -> None:
        await self.set_status(principal, document_id, DocumentStatus.DELETED)


class MemoryJobQueue:
    def __init__(self) -> None:
        self.jobs: dict[str, IngestionJobState] = {}

    async def publish(
        self,
        job: IngestionJobState,
        *,
        replace_completed: bool = False,
    ) -> None:
        if replace_completed or job.job_id not in self.jobs:
            self.jobs[job.job_id] = job
