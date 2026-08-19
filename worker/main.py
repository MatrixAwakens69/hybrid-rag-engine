"""Phase 0 worker process with graceful shutdown and no ingestion behavior."""

from __future__ import annotations

import asyncio
import signal
from contextlib import suppress

import structlog
from qdrant_client import AsyncQdrantClient

from app.api.logging import configure_logging
from app.application.worker_pipeline import WorkerPipeline
from app.config import get_settings
from app.infrastructure.chunking.structure_aware import StructureAwareChunker
from app.infrastructure.filesystem.document_storage import DocumentFileStorage
from app.infrastructure.filesystem.manifest_queue import ManifestQueue
from app.infrastructure.parsers.docling_pdf import DoclingPDFParser
from app.infrastructure.parsers.router import ParserRouter
from app.infrastructure.parsers.text import CSVParser, LogParser, MarkdownParser, PlainTextParser
from app.infrastructure.repositories.qdrant_documents import QdrantDocumentRepository

logger = structlog.get_logger(__name__)


async def run() -> None:
    """Stay alive for Compose while Phase 1 adds manifest processing."""

    settings = get_settings()
    configure_logging(settings.log_level)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signal_name in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(signal_name, stop.set)

    client = AsyncQdrantClient(
        url=settings.qdrant_url,
        timeout=settings.qdrant_timeout_seconds,
    )
    repository = QdrantDocumentRepository(client, settings.qdrant_document_collection)
    queue = ManifestQueue(settings.job_manifest_path)
    storage = DocumentFileStorage(settings.quarantine_path, settings.source_volume_path)
    parsers = ParserRouter(
        pdf=DoclingPDFParser(
            settings.parser_version,
            max_pages=settings.max_pdf_pages,
            max_characters=settings.max_element_characters,
            timeout_seconds=settings.parse_timeout_seconds,
        ),
        text=PlainTextParser(
            settings.parser_version,
            max_lines=settings.max_text_lines,
            max_characters=settings.max_element_characters,
        ),
        markdown=MarkdownParser(
            settings.parser_version,
            max_lines=settings.max_text_lines,
            max_characters=settings.max_element_characters,
        ),
        csv_parser=CSVParser(
            settings.parser_version,
            max_lines=settings.max_text_lines,
            max_characters=settings.max_element_characters,
            max_rows=settings.max_csv_rows,
            max_columns=settings.max_csv_columns,
        ),
        log=LogParser(
            settings.parser_version,
            max_lines=settings.max_text_lines,
            max_characters=settings.max_element_characters,
        ),
    )
    chunker = StructureAwareChunker(
        settings.chunker_version,
        target_tokens=settings.chunk_target_tokens,
        max_tokens=settings.chunk_max_tokens,
        overlap_tokens=settings.chunk_overlap_tokens,
    )
    pipeline = WorkerPipeline(
        queue,
        repository,
        storage,
        parsers,
        chunker,
        app_revision=settings.app_revision,
        collection_alias=settings.qdrant_collection_alias,
    )
    await repository.initialize()
    await queue.initialize()
    await storage.initialize()
    recovered = await queue.recover_stale(settings.manifest_stale_seconds)
    logger.info("worker_started", revision=settings.app_revision, recovered_jobs=recovered)
    try:
        while not stop.is_set():
            processed = await pipeline.process_one()
            if processed:
                continue
            try:
                await asyncio.wait_for(stop.wait(), timeout=settings.worker_poll_seconds)
            except TimeoutError:
                continue
    finally:
        await client.close()
        logger.info("worker_stopped")


def main() -> None:
    """Run the worker process."""

    asyncio.run(run())


if __name__ == "__main__":
    main()
