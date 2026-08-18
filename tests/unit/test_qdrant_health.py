"""Qdrant readiness adapter behavior."""

from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest

from app.domain.errors import DependencyUnavailableError
from app.domain.models import HealthStatus
from app.infrastructure.qdrant_health import QdrantReadinessProbe


@pytest.mark.asyncio
async def test_qdrant_probe_reports_connectivity() -> None:
    client = Mock()
    client.get_collections = AsyncMock(return_value=object())

    result = await QdrantReadinessProbe(client).check()

    assert result["qdrant"].status is HealthStatus.OK
    assert result["qdrant"].latency_ms is not None


@pytest.mark.asyncio
async def test_qdrant_probe_hides_dependency_error_details() -> None:
    client = Mock()
    client.get_collections = AsyncMock(side_effect=RuntimeError("sensitive endpoint detail"))

    with pytest.raises(DependencyUnavailableError):
        await QdrantReadinessProbe(client).check()
