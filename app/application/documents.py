"""Authenticated document lifecycle use cases."""

from __future__ import annotations

from collections.abc import AsyncIterable, Sequence
from datetime import UTC, datetime
from pathlib import Path, PurePath
from typing import Protocol

from app.domain.errors import DocumentNotFoundError, ForbiddenError
from app.domain.models import (
    DocumentMetadata,
    DocumentRecord,
    DocumentStatus,
    IngestionJobState,
    JobOperation,
    TenantPrincipal,
    VersionManifest,
)
from app.domain.models.documents import MetadataValue
from app.domain.models.ingestion import JobClaimState
from app.domain.policies.ids import deletion_job_id, document_version_id, ingestion_job_id
from app.domain.policies.uploads import (
    sanitize_filename,
    validate_upload_type,
    validate_user_metadata,
)
from app.domain.protocols import DocumentRepository
from app.domain.uploads import StagedUpload


class UploadStorage(Protocol):
    async def stage(
        self,
        principal: TenantPrincipal,
        chunks: AsyncIterable[bytes],
        *,
        max_bytes: int,
    ) -> StagedUpload: ...

    async def promote(
        self,
        staged: StagedUpload,
        principal: TenantPrincipal,
        document_id: str,
        source_suffix: str,
    ) -> Path: ...

    async def discard(self, staged: StagedUpload) -> None: ...


class JobQueue(Protocol):
    async def publish(
        self,
        job: IngestionJobState,
        *,
        replace_completed: bool = False,
    ) -> None: ...


class DocumentService:
    """Orchestrate secure, idempotent document acceptance and deletion."""

    def __init__(
        self,
        repository: DocumentRepository,
        storage: UploadStorage,
        queue: JobQueue,
        *,
        parser_version: str,
        chunker_version: str,
        index_schema_version: str,
        app_revision: str,
        max_upload_bytes: int,
        max_metadata_bytes: int,
    ) -> None:
        self._repository = repository
        self._storage = storage
        self._queue = queue
        self._parser_version = parser_version
        self._chunker_version = chunker_version
        self._index_schema_version = index_schema_version
        self._app_revision = app_revision
        self._max_upload_bytes = max_upload_bytes
        self._max_metadata_bytes = max_metadata_bytes

    async def upload(
        self,
        principal: TenantPrincipal,
        *,
        filename: str,
        content_type: str,
        metadata: dict[str, MetadataValue],
        chunks: AsyncIterable[bytes],
        force_reindex: bool,
    ) -> DocumentRecord:
        self._require_scope(principal, "documents:write")
        if force_reindex:
            self._require_scope(principal, "ingestion:force_reindex")
        safe_filename = sanitize_filename(filename)
        safe_metadata = validate_user_metadata(metadata, self._max_metadata_bytes)
        staged = await self._storage.stage(
            principal,
            chunks,
            max_bytes=self._max_upload_bytes,
        )
        try:
            normalized_type = validate_upload_type(
                safe_filename,
                content_type,
                staged.first_bytes,
            )
            suffix = PurePath(safe_filename).suffix.lower()
            document_id = document_version_id(
                principal.tenant_id,
                staged.checksum_sha256,
                self._parser_version,
                self._chunker_version,
                self._index_schema_version,
            )
            existing = await self._repository.get(principal, document_id)
            if (
                existing is not None
                and not force_reindex
                and (existing.document.status is not DocumentStatus.DELETED)
            ):
                await self._storage.discard(staged)
                return existing

            await self._storage.promote(staged, principal, document_id, suffix)
            now = datetime.now(UTC)
            versions = self._versions()
            record = DocumentRecord(
                tenant_id=principal.tenant_id,
                document=DocumentMetadata(
                    document_id=document_id,
                    filename=safe_filename,
                    content_type=normalized_type,
                    checksum_sha256=staged.checksum_sha256,
                    status=DocumentStatus.ACCEPTED,
                    user_metadata=safe_metadata,
                    created_at=existing.document.created_at if existing else now,
                    updated_at=now,
                ),
                versions=versions,
            )
            await self._repository.upsert(principal, record)
            job = IngestionJobState(
                job_id=ingestion_job_id(document_id, staged.checksum_sha256),
                document_id=document_id,
                document_version_id=document_id,
                tenant_id=principal.tenant_id,
                operation=JobOperation.INGEST,
                claim_state=JobClaimState.PENDING,
                stage=DocumentStatus.ACCEPTED,
                checksum_sha256=staged.checksum_sha256,
                filename=safe_filename,
                content_type=normalized_type,
                source_suffix=suffix,
                user_metadata=safe_metadata,
                parser_version=self._parser_version,
                chunker_version=self._chunker_version,
                index_schema_version=self._index_schema_version,
                created_at=now,
                updated_at=now,
            )
            await self._queue.publish(job, replace_completed=force_reindex)
            return record
        except Exception:
            if staged.path.exists():
                await self._storage.discard(staged)
            raise

    async def get(self, principal: TenantPrincipal, document_id: str) -> DocumentRecord:
        self._require_scope(principal, "documents:read")
        record = await self._repository.get(principal, document_id)
        if record is None:
            raise DocumentNotFoundError()
        return record

    async def list(
        self,
        principal: TenantPrincipal,
        *,
        cursor: str | None,
        limit: int,
    ) -> tuple[Sequence[DocumentRecord], str | None]:
        self._require_scope(principal, "documents:read")
        return await self._repository.list(principal, cursor=cursor, limit=limit)

    async def delete(self, principal: TenantPrincipal, document_id: str) -> DocumentRecord:
        self._require_scope(principal, "documents:delete")
        record = await self._repository.get(principal, document_id)
        if record is None:
            raise DocumentNotFoundError()
        if record.document.status in {DocumentStatus.DELETING, DocumentStatus.DELETED}:
            return record
        await self._repository.set_status(principal, document_id, DocumentStatus.DELETING)
        now = datetime.now(UTC)
        job = IngestionJobState(
            job_id=deletion_job_id(document_id),
            document_id=document_id,
            document_version_id=document_id,
            tenant_id=principal.tenant_id,
            operation=JobOperation.DELETE,
            claim_state=JobClaimState.PENDING,
            stage=DocumentStatus.DELETING,
            parser_version=self._parser_version,
            chunker_version=self._chunker_version,
            index_schema_version=self._index_schema_version,
            created_at=now,
            updated_at=now,
        )
        await self._queue.publish(job)
        updated = await self._repository.get(principal, document_id)
        if updated is None:
            raise DocumentNotFoundError()
        return updated

    def _versions(self) -> VersionManifest:
        return VersionManifest(
            app_revision=self._app_revision,
            index_schema_version=self._index_schema_version,
            parser_version=self._parser_version,
            chunker_version=self._chunker_version,
        )

    @staticmethod
    def _require_scope(principal: TenantPrincipal, scope: str) -> None:
        if scope not in principal.scopes:
            raise ForbiddenError()
