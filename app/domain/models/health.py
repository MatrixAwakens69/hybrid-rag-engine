"""Operational health contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field

from app.domain.models.common import ContractModel


class HealthStatus(StrEnum):
    """Service health states."""

    OK = "ok"
    NOT_READY = "not_ready"


class DependencyHealth(ContractModel):
    """Safe readiness state for one required dependency."""

    status: HealthStatus
    latency_ms: float | None = Field(default=None, ge=0)


class HealthResponse(ContractModel):
    """Liveness or readiness response."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    status: HealthStatus
    service: Annotated[str, Field(min_length=1, max_length=128)]
    revision: Annotated[str, Field(min_length=1, max_length=128)]
    dependencies: dict[str, DependencyHealth] = Field(default_factory=dict, max_length=16)
