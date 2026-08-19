"""Deterministic ID, upload, and lifecycle policies."""

from __future__ import annotations

import pytest
from hypothesis import given
from hypothesis import strategies as st

from app.domain.errors import InvalidUploadError, UnsupportedMediaTypeError
from app.domain.models import DocumentStatus
from app.domain.policies.ids import chunk_id, document_version_id
from app.domain.policies.lifecycle import can_transition, require_transition
from app.domain.policies.uploads import (
    sanitize_filename,
    validate_upload_type,
    validate_user_metadata,
)


@given(st.text(alphabet="abcdef0123456789", min_size=64, max_size=64))
def test_document_ids_are_stable_and_tenant_scoped(checksum: str) -> None:
    first = document_version_id("tenant-a", checksum, "parser-v1", "chunk-v1", "index-v1")
    repeated = document_version_id("tenant-a", checksum, "parser-v1", "chunk-v1", "index-v1")
    other_tenant = document_version_id(
        "tenant-b",
        checksum,
        "parser-v1",
        "chunk-v1",
        "index-v1",
    )

    assert first == repeated
    assert first != other_tenant


def test_chunk_id_changes_with_source_span() -> None:
    first = chunk_id("document", ["Heading"], '{"line_start":1}', 0)
    second = chunk_id("document", ["Heading"], '{"line_start":2}', 0)

    assert first != second


def test_filename_is_display_only_and_sanitized() -> None:
    assert sanitize_filename("../../tenant-b/secret?.pdf") == "secret_.pdf"
    assert sanitize_filename("..\\..\\evil.log") == "evil.log"


def test_pdf_signature_must_match_declared_type() -> None:
    assert validate_upload_type("report.pdf", "application/pdf", b"%PDF-1.7") == "application/pdf"
    with pytest.raises(UnsupportedMediaTypeError):
        validate_upload_type("report.pdf", "application/pdf", b"not a pdf")


def test_text_rejects_binary_nul_content() -> None:
    with pytest.raises(InvalidUploadError):
        validate_upload_type("notes.txt", "text/plain", b"text\x00binary")


def test_metadata_is_bounded_and_reserves_internal_keys() -> None:
    assert validate_user_metadata({"department": "legal"}, 1024) == {"department": "legal"}
    with pytest.raises(InvalidUploadError):
        validate_user_metadata({"_tenant_id": "forged"}, 1024)
    with pytest.raises(InvalidUploadError):
        validate_user_metadata({"large": "x" * 100}, 10)


def test_lifecycle_rejects_skipped_processing_states() -> None:
    assert can_transition(DocumentStatus.ACCEPTED, DocumentStatus.PARSING)
    assert can_transition(DocumentStatus.READY, DocumentStatus.DELETING)
    with pytest.raises(ValueError, match="invalid document status transition"):
        require_transition(DocumentStatus.ACCEPTED, DocumentStatus.READY)
