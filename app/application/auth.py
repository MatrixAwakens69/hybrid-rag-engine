"""Authentication application boundary."""

from __future__ import annotations

from typing import Protocol

from app.domain.models import TenantPrincipal


class Authenticator(Protocol):
    """Authenticate a raw bearer token without exposing its stored hash."""

    async def authenticate(self, token: str) -> TenantPrincipal: ...
