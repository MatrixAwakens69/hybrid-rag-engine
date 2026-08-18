"""Health-check application boundary."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import DependencyHealth


class ReadinessProbe(Protocol):
    """Check required dependencies without invoking paid model APIs."""

    async def check(self) -> dict[str, DependencyHealth]: ...
