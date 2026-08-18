"""Unauthenticated liveness and dependency readiness endpoints."""

from __future__ import annotations

from typing import cast

from fastapi import APIRouter, Request

from app.application.health import ReadinessProbe
from app.config import Settings
from app.domain.models import ErrorResponse, HealthResponse, HealthStatus

router = APIRouter(prefix="/health", tags=["health"])


def _settings(request: Request) -> Settings:
    return cast(Settings, request.app.state.settings)


def _readiness_probe(request: Request) -> ReadinessProbe:
    return cast(ReadinessProbe, request.app.state.readiness_probe)


@router.get("/live", response_model=HealthResponse)
async def live(request: Request) -> HealthResponse:
    """Report only process and event-loop liveness."""

    settings = _settings(request)
    return HealthResponse(
        status=HealthStatus.OK,
        service="hybrid-rag-engine",
        revision=settings.app_revision,
    )


@router.get(
    "/ready",
    response_model=HealthResponse,
    responses={503: {"model": ErrorResponse}},
)
async def ready(request: Request) -> HealthResponse:
    """Report configuration and Qdrant connectivity without model calls."""

    settings = _settings(request)
    dependencies = await _readiness_probe(request).check()
    return HealthResponse(
        status=HealthStatus.OK,
        service="hybrid-rag-engine",
        revision=settings.app_revision,
        dependencies=dependencies,
    )
