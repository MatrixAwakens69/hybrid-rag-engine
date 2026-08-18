"""Safe application errors independent of HTTP."""

from __future__ import annotations


class ServiceError(Exception):
    """Expected failure safe to map to a public error response."""

    code = "service_error"
    public_message = "The service could not complete the request."
    retryable = False

    def __init__(self, *, public_message: str | None = None) -> None:
        super().__init__(public_message or self.public_message)
        self.public_message = public_message or self.public_message


class DependencyUnavailableError(ServiceError):
    """A required dependency is unavailable."""

    code = "dependency_unavailable"
    public_message = "A required service dependency is unavailable."
    retryable = True
