"""Version-one retrieval and grounded-answer contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import Field, model_validator

from app.domain.models.common import ContractModel, Identifier, VersionManifest
from app.domain.models.documents import MetadataValue


class AnswerStatus(StrEnum):
    """Successful query outcomes."""

    ANSWERED = "answered"
    ABSTAINED = "abstained"


class RetrievalControls(ContractModel):
    """Bounded caller controls; server policy may lower these values."""

    dense_candidates: int | None = Field(default=None, ge=1, le=200)
    sparse_candidates: int | None = Field(default=None, ge=1, le=200)
    rerank_top_k: int | None = Field(default=None, ge=1, le=50)


class QueryRequest(ContractModel):
    """Tenant-scoped question and optional evidence filters."""

    question: Annotated[str, Field(min_length=1, max_length=8000)]
    document_ids: list[Identifier] = Field(default_factory=list, max_length=100)
    metadata_filters: dict[str, MetadataValue] = Field(default_factory=dict, max_length=32)
    retrieval: RetrievalControls = Field(default_factory=RetrievalControls)
    client_request_id: Identifier | None = None


class SourceLocation(ContractModel):
    """Precise source span when supplied by the parser."""

    page_start: int | None = Field(default=None, ge=1)
    page_end: int | None = Field(default=None, ge=1)
    line_start: int | None = Field(default=None, ge=1)
    line_end: int | None = Field(default=None, ge=1)
    row_start: int | None = Field(default=None, ge=1)
    row_end: int | None = Field(default=None, ge=1)
    hierarchy_path: list[str] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def validate_ranges(self) -> SourceLocation:
        for start_name, end_name in (
            ("page_start", "page_end"),
            ("line_start", "line_end"),
            ("row_start", "row_end"),
        ):
            start = getattr(self, start_name)
            end = getattr(self, end_name)
            if start is not None and end is not None and end < start:
                raise ValueError(f"{end_name} cannot be less than {start_name}")
        return self


class EvidenceItem(ContractModel):
    """Bounded evidence supplied to and cited by the generator."""

    evidence_id: Identifier
    document_id: Identifier
    excerpt: Annotated[str, Field(min_length=1, max_length=12000)]
    location: SourceLocation
    score: float | None = None


class Citation(ContractModel):
    """A material answer claim linked to allowed evidence."""

    evidence_ids: list[Identifier] = Field(min_length=1, max_length=20)
    claim: Annotated[str, Field(min_length=1, max_length=2000)]


class AnswerResponse(ContractModel):
    """Validated grounded answer or explicit abstention."""

    schema_version: str = Field(default="v1", pattern=r"^v1$")
    status: AnswerStatus
    answer: Annotated[str, Field(max_length=20000)]
    evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    citations: list[Citation] = Field(default_factory=list, max_length=100)
    warnings: list[str] = Field(default_factory=list, max_length=50)
    request_id: Identifier
    versions: VersionManifest

    @model_validator(mode="after")
    def validate_status_consistency(self) -> AnswerResponse:
        allowed_evidence = {item.evidence_id for item in self.evidence}
        cited_evidence = {item for citation in self.citations for item in citation.evidence_ids}
        unknown = cited_evidence - allowed_evidence
        if unknown:
            raise ValueError(f"citations reference unknown evidence IDs: {sorted(unknown)}")
        if self.status is AnswerStatus.ANSWERED and (not self.answer or not self.citations):
            raise ValueError("answered responses require answer text and citations")
        if self.status is AnswerStatus.ABSTAINED and self.citations:
            raise ValueError("abstained responses cannot assert citations")
        return self
