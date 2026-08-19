"""End-to-end Phase 1 lifecycle using durable files and in-memory control records."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.application.documents import DocumentService
from app.application.worker_pipeline import WorkerPipeline
from app.domain.models import DocumentStatus, TenantPrincipal
from app.infrastructure.chunking.structure_aware import StructureAwareChunker
from app.infrastructure.filesystem.document_storage import DocumentFileStorage
from app.infrastructure.filesystem.manifest_queue import ManifestQueue
from app.infrastructure.parsers.docling_pdf import DoclingPDFParser
from app.infrastructure.parsers.router import ParserRouter
from app.infrastructure.parsers.text import CSVParser, LogParser, MarkdownParser, PlainTextParser
from tests.fakes import MemoryDocumentRepository


async def _content(value: bytes):
    yield value


def _parsers() -> ParserRouter:
    common = {"max_lines": 1000, "max_characters": 100_000}
    return ParserRouter(
        pdf=DoclingPDFParser(
            "parser-v1",
            max_pages=10,
            max_characters=100_000,
            timeout_seconds=30,
        ),
        text=PlainTextParser("parser-v1", **common),
        markdown=MarkdownParser("parser-v1", **common),
        csv_parser=CSVParser(
            "parser-v1",
            **common,
            max_rows=1000,
            max_columns=100,
        ),
        log=LogParser("parser-v1", **common),
    )


@pytest.mark.integration
@pytest.mark.asyncio
async def test_upload_process_idempotent_resubmit_and_delete(tmp_path: Path) -> None:
    repository = MemoryDocumentRepository()
    queue = ManifestQueue(tmp_path / "jobs")
    storage = DocumentFileStorage(tmp_path / "quarantine", tmp_path / "sources")
    await queue.initialize()
    await storage.initialize()
    service = DocumentService(
        repository,
        storage,
        queue,
        parser_version="parser-v1",
        chunker_version="chunk-v1",
        index_schema_version="v1",
        app_revision="test",
        max_upload_bytes=1024 * 1024,
        max_metadata_bytes=1024,
    )
    pipeline = WorkerPipeline(
        queue,
        repository,
        storage,
        _parsers(),
        StructureAwareChunker(
            "chunk-v1",
            target_tokens=40,
            max_tokens=60,
            overlap_tokens=5,
        ),
        app_revision="test",
        collection_alias="hybrid_chunks_current",
    )
    principal = TenantPrincipal(
        tenant_id="tenant-a",
        key_id="key-a",
        scopes=frozenset(
            {
                "documents:read",
                "documents:write",
                "documents:delete",
                "ingestion:force_reindex",
            }
        ),
    )

    accepted = await service.upload(
        principal,
        filename="guide.md",
        content_type="text/markdown",
        metadata={"department": "engineering"},
        chunks=_content(b"# Deploy\n\nUse the verified release artifact.\n"),
        force_reindex=False,
    )
    assert accepted.document.status is DocumentStatus.ACCEPTED

    assert await pipeline.process_one()
    ready = await service.get(principal, accepted.document.document_id)
    assert ready.document.status is DocumentStatus.READY
    root = storage.document_root(principal.tenant_id, ready.document.document_id)
    chunks = json.loads((root / "chunks.json").read_text(encoding="utf-8"))
    assert chunks
    assert chunks[0]["tenant_id"] == principal.tenant_id
    assert chunks[0]["checksum_sha256"] == ready.document.checksum_sha256
    assert chunks[0]["parser_version"] == "parser-v1"
    assert chunks[0]["chunker_version"] == "chunk-v1"

    repeated = await service.upload(
        principal,
        filename="guide.md",
        content_type="text/markdown",
        metadata={"department": "engineering"},
        chunks=_content(b"# Deploy\n\nUse the verified release artifact.\n"),
        force_reindex=False,
    )
    assert repeated.document.document_id == ready.document.document_id
    assert await pipeline.process_one() is False

    deleting = await service.delete(principal, ready.document.document_id)
    assert deleting.document.status is DocumentStatus.DELETING
    assert await pipeline.process_one()
    deleted = await service.get(principal, ready.document.document_id)
    assert deleted.document.status is DocumentStatus.DELETED
    assert not root.exists()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_parse_failure_is_terminal_and_worker_continues(tmp_path: Path) -> None:
    repository = MemoryDocumentRepository()
    queue = ManifestQueue(tmp_path / "jobs")
    storage = DocumentFileStorage(tmp_path / "quarantine", tmp_path / "sources")
    await queue.initialize()
    await storage.initialize()
    service = DocumentService(
        repository,
        storage,
        queue,
        parser_version="parser-v1",
        chunker_version="chunk-v1",
        index_schema_version="v1",
        app_revision="test",
        max_upload_bytes=1024,
        max_metadata_bytes=1024,
    )
    pipeline = WorkerPipeline(
        queue,
        repository,
        storage,
        _parsers(),
        StructureAwareChunker(
            "chunk-v1",
            target_tokens=40,
            max_tokens=60,
            overlap_tokens=5,
        ),
        app_revision="test",
        collection_alias="hybrid_chunks_current",
    )
    principal = TenantPrincipal(
        tenant_id="tenant-a",
        key_id="key-a",
        scopes=frozenset({"documents:read", "documents:write"}),
    )
    accepted = await service.upload(
        principal,
        filename="empty.txt",
        content_type="text/plain",
        metadata={},
        chunks=_content(b"   \n\n"),
        force_reindex=False,
    )

    assert await pipeline.process_one()
    failed = await service.get(principal, accepted.document.document_id)
    assert failed.document.status is DocumentStatus.FAILED
    assert failed.failure_code == "processing_failed"
    assert await pipeline.process_one() is False
