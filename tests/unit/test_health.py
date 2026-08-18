"""Liveness, readiness, request-ID, and safe-error behavior."""

from __future__ import annotations

import httpx
import pytest

from app.config import Settings
from app.domain.errors import DependencyUnavailableError
from app.main import create_app


class FailingProbe:
    async def check(self) -> dict[str, object]:
        raise DependencyUnavailableError()


class MustNotRunProbe:
    async def check(self) -> dict[str, object]:
        raise AssertionError("liveness must not check dependencies")


@pytest.mark.asyncio
async def test_liveness_does_not_check_qdrant(test_settings: Settings) -> None:
    app = create_app(test_settings, MustNotRunProbe())
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get("/health/live")

    assert response.status_code == 200
    assert response.json() == {
        "schema_version": "v1",
        "status": "ok",
        "service": "hybrid-rag-engine",
        "revision": "test-revision",
        "dependencies": {},
    }


@pytest.mark.asyncio
async def test_readiness_reports_qdrant_without_model_calls(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/ready")

    assert response.status_code == 200
    assert response.json()["dependencies"]["qdrant"]["status"] == "ok"
    assert response.json()["dependencies"]["qdrant"]["latency_ms"] == 1.0


@pytest.mark.asyncio
async def test_dependency_failure_maps_to_safe_retryable_error(
    test_settings: Settings,
) -> None:
    app = create_app(test_settings, FailingProbe())
    transport = httpx.ASGITransport(app=app)
    async with (
        app.router.lifespan_context(app),
        httpx.AsyncClient(transport=transport, base_url="http://test") as client,
    ):
        response = await client.get(
            "/health/ready",
            headers={"X-Request-ID": "request-123"},
        )

    assert response.status_code == 503
    assert response.headers["X-Request-ID"] == "request-123"
    assert response.json() == {
        "schema_version": "v1",
        "error": {
            "code": "dependency_unavailable",
            "message": "A required service dependency is unavailable.",
            "request_id": "request-123",
            "retryable": True,
            "field_violations": [],
        },
    }


@pytest.mark.asyncio
async def test_invalid_request_id_is_replaced(client: httpx.AsyncClient) -> None:
    response = await client.get("/health/live", headers={"X-Request-ID": "bad request id\n"})

    assert response.status_code == 200
    assert response.headers["X-Request-ID"] != "bad request id\n"
    assert len(response.headers["X-Request-ID"]) == 32
