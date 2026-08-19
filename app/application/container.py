"""Application services exposed to API dependencies."""

from __future__ import annotations

from dataclasses import dataclass

from app.application.auth import Authenticator
from app.application.documents import DocumentService


@dataclass(frozen=True)
class ApplicationServices:
    """Explicit API composition boundary."""

    authenticator: Authenticator
    documents: DocumentService
