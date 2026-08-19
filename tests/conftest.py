"""Shared deterministic test adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.application.container import ApplicationServices
from app.application.documents import DocumentService
from app.config import Environment, Settings
from app.domain.models import DependencyHealth, HealthStatus
from app.infrastructure.filesystem.document_storage import DocumentFileStorage
from app.main import create_app
from tests.fakes import MemoryAuthenticator, MemoryDocumentRepository, MemoryJobQueue


class HealthyReadinessProbe:
    """Readiness adapter with no network dependency."""

    async def check(self) -> dict[str, DependencyHealth]:
        return {"qdrant": DependencyHealth(status=HealthStatus.OK, latency_ms=1.0)}


@pytest.fixture
def test_settings(tmp_path: Path) -> Settings:
    return Settings(
        _env_file=None,
        environment=Environment.TEST,
        app_revision="test-revision",
        source_volume_path=tmp_path / "sources",
        job_manifest_path=tmp_path / "jobs",
        quarantine_path=tmp_path / "quarantine",
    )


@pytest.fixture
async def client(test_settings: Settings) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, HealthyReadinessProbe())
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as test_client,
    ):
        yield test_client


@pytest.fixture
def phase1_repository() -> MemoryDocumentRepository:
    return MemoryDocumentRepository()


@pytest.fixture
def phase1_queue() -> MemoryJobQueue:
    return MemoryJobQueue()


@pytest.fixture
async def phase1_services(
    test_settings: Settings,
    phase1_repository: MemoryDocumentRepository,
    phase1_queue: MemoryJobQueue,
) -> ApplicationServices:
    storage = DocumentFileStorage(
        test_settings.quarantine_path,
        test_settings.source_volume_path,
    )
    await storage.initialize()
    return ApplicationServices(
        authenticator=MemoryAuthenticator(),
        documents=DocumentService(
            phase1_repository,
            storage,
            phase1_queue,
            parser_version=test_settings.parser_version,
            chunker_version=test_settings.chunker_version,
            index_schema_version=test_settings.index_schema_version,
            app_revision=test_settings.app_revision,
            max_upload_bytes=test_settings.max_upload_bytes,
            max_metadata_bytes=test_settings.max_metadata_bytes,
        ),
    )


@pytest.fixture
async def phase1_client(
    test_settings: Settings,
    phase1_services: ApplicationServices,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(test_settings, HealthyReadinessProbe(), phase1_services)
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as test_client,
    ):
        yield test_client
