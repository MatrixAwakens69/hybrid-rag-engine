"""FastAPI composition root."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from qdrant_client import AsyncQdrantClient

from app.api.errors import register_exception_handlers
from app.api.health import router as health_router
from app.api.logging import configure_logging
from app.api.middleware import RequestContextMiddleware
from app.application.health import ReadinessProbe
from app.config import Settings, get_settings
from app.infrastructure.qdrant_health import QdrantReadinessProbe


def create_app(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
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
        else:
            app.state.readiness_probe = readiness_probe
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
    return app


app = create_app()
