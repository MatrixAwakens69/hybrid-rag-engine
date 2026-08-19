"""Document lifecycle transition policy."""

from __future__ import annotations

from app.domain.models.documents import DocumentStatus

_ALLOWED_TRANSITIONS: dict[DocumentStatus, frozenset[DocumentStatus]] = {
    DocumentStatus.ACCEPTED: frozenset(
        {DocumentStatus.PARSING, DocumentStatus.DELETING, DocumentStatus.FAILED}
    ),
    DocumentStatus.PARSING: frozenset(
        {DocumentStatus.CHUNKING, DocumentStatus.DELETING, DocumentStatus.FAILED}
    ),
    DocumentStatus.CHUNKING: frozenset(
        {DocumentStatus.INDEXING, DocumentStatus.DELETING, DocumentStatus.FAILED}
    ),
    DocumentStatus.INDEXING: frozenset(
        {DocumentStatus.READY, DocumentStatus.DELETING, DocumentStatus.FAILED}
    ),
    DocumentStatus.READY: frozenset({DocumentStatus.ACCEPTED, DocumentStatus.DELETING}),
    DocumentStatus.FAILED: frozenset({DocumentStatus.ACCEPTED, DocumentStatus.DELETING}),
    DocumentStatus.DELETING: frozenset({DocumentStatus.DELETED}),
    DocumentStatus.DELETED: frozenset({DocumentStatus.ACCEPTED}),
}


def can_transition(current: DocumentStatus, target: DocumentStatus) -> bool:
    """Return whether a lifecycle update is valid and idempotent."""

    return current is target or target in _ALLOWED_TRANSITIONS[current]


def require_transition(current: DocumentStatus, target: DocumentStatus) -> None:
    """Reject programming errors that would corrupt lifecycle state."""

    if not can_transition(current, target):
        raise ValueError(f"invalid document status transition: {current} -> {target}")
