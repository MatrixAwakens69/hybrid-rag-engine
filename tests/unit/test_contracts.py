"""Semantic validation for version-one public contracts."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.models.common import VersionManifest
from app.domain.models.query import (
    AnswerResponse,
    AnswerStatus,
    Citation,
    EvidenceItem,
    SourceLocation,
)


def _versions() -> VersionManifest:
    return VersionManifest(app_revision="test", index_schema_version="v1")


def _evidence() -> EvidenceItem:
    return EvidenceItem(
        evidence_id="chunk-1",
        document_id="document-1",
        excerpt="Grounded evidence.",
        location=SourceLocation(page_start=1, page_end=1),
    )


def test_answer_requires_known_evidence_ids() -> None:
    with pytest.raises(ValidationError, match="unknown evidence IDs"):
        AnswerResponse(
            status=AnswerStatus.ANSWERED,
            answer="An answer.",
            evidence=[_evidence()],
            citations=[Citation(evidence_ids=["chunk-2"], claim="An answer.")],
            request_id="request-1",
            versions=_versions(),
        )


def test_answered_response_requires_citations() -> None:
    with pytest.raises(ValidationError, match="require answer text and citations"):
        AnswerResponse(
            status=AnswerStatus.ANSWERED,
            answer="An answer.",
            evidence=[_evidence()],
            citations=[],
            request_id="request-1",
            versions=_versions(),
        )


def test_abstention_cannot_assert_citations() -> None:
    with pytest.raises(ValidationError, match="cannot assert citations"):
        AnswerResponse(
            status=AnswerStatus.ABSTAINED,
            answer="Insufficient evidence.",
            evidence=[_evidence()],
            citations=[Citation(evidence_ids=["chunk-1"], claim="A claim.")],
            request_id="request-1",
            versions=_versions(),
        )


def test_source_location_rejects_reversed_ranges() -> None:
    with pytest.raises(ValidationError, match="page_end"):
        SourceLocation(page_start=3, page_end=2)
