"""Shared deterministic test adapters."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

from app.config import Environment, Settings
from app.domain.models import DependencyHealth, HealthStatus
from app.main import create_app


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
