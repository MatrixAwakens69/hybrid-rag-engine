"""Shared API dependencies for authenticated version-one routes."""

from __future__ import annotations

from typing import Annotated, cast

from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.application.container import ApplicationServices
from app.domain.errors import DependencyUnavailableError, UnauthorizedError
from app.domain.models import TenantPrincipal

_bearer = HTTPBearer(auto_error=False)


def get_services(request: Request) -> ApplicationServices:
    services = getattr(request.app.state, "services", None)
    if services is None:
        raise DependencyUnavailableError()
    return cast(ApplicationServices, services)


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    services: Annotated[ApplicationServices, Depends(get_services)],
) -> TenantPrincipal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise UnauthorizedError()
    return await services.authenticator.authenticate(credentials.credentials)


ServicesDependency = Annotated[ApplicationServices, Depends(get_services)]
PrincipalDependency = Annotated[TenantPrincipal, Depends(get_current_principal)]
