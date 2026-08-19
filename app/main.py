"""FastAPI composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient

from app.api.documents import router as documents_router
from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.logging import configure_logging
from app.api.middleware import RequestContextMiddleware
from app.application.container import ApplicationServices
from app.application.documents import DocumentService
from app.application.health import ReadinessProbe
from app.config import Settings, get_settings
from app.infrastructure.auth.qdrant_api_keys import QdrantAPIKeyAuthenticator
from app.infrastructure.filesystem.document_storage import DocumentFileStorage
from app.infrastructure.filesystem.manifest_queue import ManifestQueue
from app.infrastructure.qdrant_health import QdrantReadinessProbe
from app.infrastructure.repositories.qdrant_documents import QdrantDocumentRepository


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    services: ApplicationServices | None = None,
) -> FastAPI:
    """Build an app with explicit seams for tests and future adapters."""

    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        client: AsyncQdrantClient | None = None
        if readiness_probe is None:
            client = AsyncQdrantClient(
                url=resolved_settings.qdrant_url,
                timeout=resolved_settings.qdrant_timeout_seconds,
            )
            app.state.readiness_probe = QdrantReadinessProbe(client)
            if services is None:
                authenticator = QdrantAPIKeyAuthenticator(
                    client,
                    resolved_settings.qdrant_auth_collection,
                    bootstrap_key_id=resolved_settings.bootstrap_key_id,
                )
                repository = QdrantDocumentRepository(
                    client,
                    resolved_settings.qdrant_document_collection,
                )
                storage = DocumentFileStorage(
                    resolved_settings.quarantine_path,
                    resolved_settings.source_volume_path,
                )
                queue = ManifestQueue(resolved_settings.job_manifest_path)
                await authenticator.initialize()
                await authenticator.seed_key(
                    key_id=resolved_settings.bootstrap_key_id,
                    tenant_id=resolved_settings.bootstrap_tenant_id,
                    raw_secret=resolved_settings.bootstrap_admin_key.get_secret_value(),
                    scopes=frozenset(resolved_settings.bootstrap_scopes),
                )
                await repository.initialize()
                await storage.initialize()
                await queue.initialize()
                app.state.services = ApplicationServices(
                    authenticator=authenticator,
                    documents=DocumentService(
                        repository,
                        storage,
                        queue,
                        parser_version=resolved_settings.parser_version,
                        chunker_version=resolved_settings.chunker_version,
                        index_schema_version=resolved_settings.index_schema_version,
                        app_revision=resolved_settings.app_revision,
                        max_upload_bytes=resolved_settings.max_upload_bytes,
                        max_metadata_bytes=resolved_settings.max_metadata_bytes,
                    ),
                )
        else:
            app.state.readiness_probe = readiness_probe
            app.state.services = services
        try:
            yield
        finally:
            if client is not None:
                await client.close()

    app = FastAPI(
        title="Hybrid RAG Engine API",
        version="0.1.0",
        description="Tenant-safe hybrid document retrieval and grounded answers.",
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.services = services
    app.add_middleware(
        CORSMiddleware,
        allow_origins=resolved_settings.cors_origins,
        allow_credentials=False,
        allow_methods=["GET", "POST", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)
    register_exception_handlers(app)
    app.include_router(health_router)
    app.include_router(documents_router)
    return app


app = create_app()
