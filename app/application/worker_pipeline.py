"""Single-job ingestion and deletion orchestration for the worker."""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path
from typing import Protocol

import structlog

from app.domain.errors import ProcessingError
from app.domain.models import (
    Chunk,
    DocumentStatus,
    DocumentWarning,
    IndexManifest,
    IngestionJobState,
    JobOperation,
    ParsedDocument,
    TenantPrincipal,
    VersionManifest,
)
from app.domain.protocols import Chunker, DocumentRepository, Parser

logger = structlog.get_logger(__name__)


class WorkerQueue(Protocol):
    async def claim_next(self) -> IngestionJobState | None: ...

    async def complete(self, job: IngestionJobState) -> None: ...

    async def fail(self, job: IngestionJobState, failure_code: str) -> None: ...

    async def remove_for_document(self, document_id: str, *, skip_job_id: str) -> None: ...


class ParserSelector(Protocol):
    def parser_for(self, filename: str) -> Parser: ...


class ArtifactStorage(Protocol):
    def source_path(self, tenant_id: str, document_id: str, source_suffix: str) -> Path: ...

    async def persist_parsed(self, document: ParsedDocument) -> None: ...

    async def persist_chunks(
        self,
        tenant_id: str,
        document_id: str,
        chunks: list[Chunk],
    ) -> None: ...

    async def persist_index_manifest(
        self,
        tenant_id: str,
        document_id: str,
        manifest: IndexManifest,
    ) -> None: ...

    async def delete_document(self, tenant_id: str, document_id: str) -> None: ...


class WorkerPipeline:
    """Process one claimed manifest without terminating the worker on bad content."""

    def __init__(
        self,
        queue: WorkerQueue,
        repository: DocumentRepository,
        storage: ArtifactStorage,
        parsers: ParserSelector,
        chunker: Chunker,
        *,
        app_revision: str,
        collection_alias: str,
    ) -> None:
        self._queue = queue
        self._repository = repository
        self._storage = storage
        self._parsers = parsers
        self._chunker = chunker
        self._app_revision = app_revision
        self._collection_alias = collection_alias

    async def process_one(self) -> bool:
        job = await self._queue.claim_next()
        if job is None:
            return False
        principal = TenantPrincipal(
            tenant_id=job.tenant_id,
            key_id="worker",
            scopes=frozenset(),
        )
        try:
            if job.operation is JobOperation.DELETE:
                await self._delete(job, principal)
            else:
                await self._ingest(job, principal)
            await self._queue.complete(job)
            return True
        except ProcessingError as exc:
            await self._mark_failed(job, principal, exc.code)
            logger.warning(
                "document_processing_failed",
                job_id=job.job_id,
                document_id=job.document_id,
                failure_code=exc.code,
            )
            return True
        except Exception as exc:
            await self._mark_failed(job, principal, "unexpected_processing_error")
            logger.exception(
                "document_processing_failed",
                job_id=job.job_id,
                document_id=job.document_id,
                error_type=type(exc).__name__,
            )
            return True

    async def _ingest(
        self,
        job: IngestionJobState,
        principal: TenantPrincipal,
    ) -> None:
        if job.filename is None or job.source_suffix is None or job.checksum_sha256 is None:
            raise ProcessingError()
        parser = self._parsers.parser_for(job.filename)
        await self._repository.set_status(
            principal,
            job.document_id,
            DocumentStatus.PARSING,
        )
        source = self._storage.source_path(
            job.tenant_id,
            job.document_id,
            job.source_suffix,
        )
        parsed = await parser.parse(
            source,
            document_id=job.document_id,
            document_version_id=job.document_version_id,
            tenant_id=job.tenant_id,
            checksum_sha256=job.checksum_sha256,
        )
        await self._storage.persist_parsed(parsed)
        await self._repository.set_status(
            principal,
            job.document_id,
            DocumentStatus.CHUNKING,
        )
        chunks = list(self._chunker.chunk(parsed))
        if not chunks:
            raise ProcessingError(public_message="No indexable chunks were produced.")
        await self._storage.persist_chunks(job.tenant_id, job.document_id, chunks)
        await self._repository.set_status(
            principal,
            job.document_id,
            DocumentStatus.INDEXING,
        )
        manifest = IndexManifest(
            document_version_id=job.document_version_id,
            collection_alias_target=self._collection_alias,
            index_schema_version=job.index_schema_version,
            chunk_count=len(chunks),
            parser_version=parsed.parser_version,
            chunker_version=self._chunker.version,
            dense_model_revision="phase2-not-indexed",
            sparse_model_revision="phase2-not-indexed",
        )
        await self._storage.persist_index_manifest(
            job.tenant_id,
            job.document_id,
            manifest,
        )
        warnings = self._warnings(parsed.warning_codes)
        await self._repository.set_status(
            principal,
            job.document_id,
            DocumentStatus.READY,
            warnings=warnings,
            versions=VersionManifest(
                app_revision=self._app_revision,
                index_schema_version=job.index_schema_version,
                parser_version=parsed.parser_version,
                chunker_version=self._chunker.version,
            ),
        )

    async def _delete(
        self,
        job: IngestionJobState,
        principal: TenantPrincipal,
    ) -> None:
        await self._storage.delete_document(job.tenant_id, job.document_id)
        await self._queue.remove_for_document(job.document_id, skip_job_id=job.job_id)
        await self._repository.set_status(
            principal,
            job.document_id,
            DocumentStatus.DELETED,
        )

    async def _mark_failed(
        self,
        job: IngestionJobState,
        principal: TenantPrincipal,
        failure_code: str,
    ) -> None:
        try:
            await self._repository.set_status(
                principal,
                job.document_id,
                DocumentStatus.FAILED,
                failure_code=failure_code,
            )
        finally:
            await self._queue.fail(job, failure_code)

    @staticmethod
    def _warnings(codes: Sequence[str]) -> list[DocumentWarning]:
        messages = {
            "encoding_fallback": "A fallback text encoding was used.",
            "ragged_csv_row": "One or more CSV rows had a different column count.",
            "unclosed_code_fence": "A Markdown code fence was not closed.",
            "unstructured_log_record": "One or more log records lacked a recognized prefix.",
        }
        return [
            DocumentWarning(code=code, message=messages.get(code, "The parser reported a warning."))
            for code in dict.fromkeys(codes)
        ]
