"""Qdrant connectivity probe used by readiness checks."""

from __future__ import annotations

from time import perf_counter

import structlog
from qdrant_client import AsyncQdrantClient

from app.domain.errors import DependencyUnavailableError
from app.domain.models import DependencyHealth, HealthStatus

logger = structlog.get_logger(__name__)


class QdrantReadinessProbe:
    """Treat successful collection discovery as Qdrant connectivity."""

    def __init__(self, client: AsyncQdrantClient) -> None:
        self._client = client

    async def check(self) -> dict[str, DependencyHealth]:
        started = perf_counter()
        try:
            await self._client.get_collections()
        except Exception as exc:
            logger.warning(
                "dependency_not_ready",
                dependency="qdrant",
                error_type=type(exc).__name__,
            )
            raise DependencyUnavailableError() from exc
        latency_ms = (perf_counter() - started) * 1000
        return {
            "qdrant": DependencyHealth(status=HealthStatus.OK, latency_ms=latency_ms),
        }
