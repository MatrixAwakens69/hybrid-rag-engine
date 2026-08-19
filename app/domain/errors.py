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


class UnauthorizedError(ServiceError):
    """Authentication is missing or invalid."""

    code = "invalid_api_key"
    public_message = "A valid API key is required."


class ForbiddenError(ServiceError):
    """The authenticated principal lacks a required scope."""

    code = "insufficient_scope"
    public_message = "The API key does not permit this operation."


class DocumentNotFoundError(ServiceError):
    """A document is absent or belongs to another tenant."""

    code = "document_not_found"
    public_message = "The requested document was not found."


class UploadTooLargeError(ServiceError):
    """The streaming upload crossed the configured byte limit."""

    code = "upload_too_large"
    public_message = "The uploaded document exceeds the configured size limit."


class UnsupportedMediaTypeError(ServiceError):
    """The file extension, media type, or signature is unsupported."""

    code = "unsupported_media_type"
    public_message = "The uploaded document type is unsupported or inconsistent."


class InvalidUploadError(ServiceError):
    """The upload is empty, malformed, or otherwise unsafe."""

    code = "invalid_upload"
    public_message = "The uploaded document is invalid."


class ManifestConflictError(ServiceError):
    """A durable job with the same identity cannot be replaced."""

    code = "manifest_conflict"
    public_message = "A conflicting ingestion job already exists."


class ProcessingError(ServiceError):
    """A deterministic parser or chunking failure."""

    code = "processing_failed"
    public_message = "The document could not be processed."


class RequestTimeoutError(ServiceError):
    """A bounded request exceeded its server-side deadline."""

    code = "request_timeout"
    public_message = "The request exceeded the configured time limit."
    retryable = True
